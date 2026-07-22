from __future__ import annotations
import base64,hashlib,io,json,os,subprocess,tempfile,unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from tools.tldr_editorial.calibration import CalibrationContext,calibrate_images,run_calibration
from tools.tldr_editorial.candidates import Candidate
from tools.tldr_editorial.core import EditorialError
from tools.tldr_editorial.image import assemble_prompt,decode_image,normalize_raster
from tools.tldr_editorial.illustration_prompts import BASELINE_PREAMBLE,BASELINE_PROFILE,PROMPT_PROFILES,PromptProfile,SHARED_FACTUAL_RESTRICTIONS
from tools.tldr_editorial.openrouter import Result
from tests_editorial.helpers import config

LEGACY="""Create a premium editorial illustration for a serious technology newspaper.

The image is an editorial illustration, not documentary photography.
Use one immediately readable focal subject.
Use a strong, restrained composition with controlled contrast.
Use sophisticated but understandable visual symbolism.
Leave useful negative space around the focal subject.
Do not render words, captions, headlines, logos, trademarks, interfaces, screenshots, charts, watermarks, or newspaper typography.
Do not fabricate visible factual evidence.
Do not imitate a named or living illustrator.
Do not create a collage of unrelated news stories.
The image must remain readable at newspaper-column and social-card sizes."""

def candidate():return Candidate("c001","issue","article","tldr","NEWS","AMD Helios rack system","AMD introduced a rack-scale AI system with physically integrated compute and networking.","https://example.com/story","example.com",3,"editorial",(0,0))
def context():return CalibrationContext("2026-07-21",{"mode":"lead_story","central_subject":"one rack-scale computing system","visual_metaphor":"industrial presence","composition":"single centered rack in a wide frame","forbidden_elements":["unsupported components"],"alt_text":"A rack-scale computing system"},(candidate(),))
def png_value():
 out=io.BytesIO();Image.new("RGB",(600,400),(80,90,100)).save(out,format="PNG");return base64.b64encode(out.getvalue()).decode()

class ImageClient:
 def __init__(self,fail=False):self.image_calls=0;self.editorial_calls=0;self.fail=fail
 def editorial(self,*a):self.editorial_calls+=1;raise AssertionError("editorial called")
 def image(self,prompt):
  self.image_calls+=1
  if self.fail:raise EditorialError("synthetic_image_failure")
  return Result(png_value(),{"prompt_tokens":10,"completion_tokens":20,"total_tokens":30,"cost_usd":0.125},None,"image/png")

class CalibrationTests(unittest.TestCase):
 def setUp(self):
  self.old=Path.cwd();self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.repo=self.base/"repo";self.repo.mkdir();os.chdir(self.repo)
  subprocess.run(["git","init","-b","main"],check=True,capture_output=True);subprocess.run(["git","config","user.email","calibration@example.com"],check=True);subprocess.run(["git","config","user.name","Calibration Test"],check=True)
  (self.repo/"tracked").write_text("clean\n");subprocess.run(["git","add","tracked"],check=True);subprocess.run(["git","commit","-m","fixture"],check=True,capture_output=True)
 def tearDown(self):os.chdir(self.old);self.tmp.cleanup()
 def output(self,name="output"):return self.base/name
 def test_baseline_exactly_reproduces_legacy_production_prompt(self):
  self.assertEqual(BASELINE_PREAMBLE,LEGACY);brief=context().brief;c=candidate()
  expected=LEGACY+"\n\nSource stories (use only these facts):\nTitle: "+c.title+"\nSummary: "+c.summary+"\n\nCentral subject: "+brief["central_subject"]+"\nVisual metaphor: "+brief["visual_metaphor"]+"\nComposition: "+brief["composition"]+"\nForbidden elements: unsupported components\n"
  self.assertEqual(assemble_prompt(brief,[c]),expected);self.assertEqual(assemble_prompt(brief,[c],BASELINE_PROFILE),expected)
 def test_profiles_are_unique_frozen_declarative_and_share_only_safety_rules(self):
  values=list(PROMPT_PROFILES.values());self.assertEqual(len({x.profile_id for x in values}),len(values));self.assertEqual(len({x.internal_id for x in values}),len(values))
  self.assertTrue(all(x.shared_factual_restrictions==SHARED_FACTUAL_RESTRICTIONS for x in values));self.assertTrue(all(x.fixed_negative_constraints for x in values));self.assertFalse(any("photoreal" in x.lower() or "gradient" in x.lower() or "synthetic" in x.lower() for x in SHARED_FACTUAL_RESTRICTIONS))
  with self.assertRaises(FrozenInstanceError):values[0].profile_id="changed"
  with self.assertRaises(TypeError):PROMPT_PROFILES["new"]=values[0]
 def test_prompt_assembly_is_deterministic_and_profiles_do_not_change_facts(self):
  prompts=[assemble_prompt(context().brief,[candidate()],p) for p in PROMPT_PROFILES.values()]
  self.assertEqual(prompts,[assemble_prompt(context().brief,[candidate()],p) for p in PROMPT_PROFILES.values()]);self.assertTrue(all(candidate().title in x and candidate().summary in x for x in prompts));self.assertGreater(len(set(prompts)),1)
 def test_dry_default_has_zero_calls_and_never_writes_official_artifacts(self):
  official=self.repo/"generated/editorial/manifest.json";official.parent.mkdir(parents=True);official.write_bytes(b"official\n");subprocess.run(["git","add","generated"],check=True);subprocess.run(["git","commit","-m","official"],check=True,capture_output=True)
  client=ImageClient();result=calibrate_images(date=context().date,profile_ids=list(PROMPT_PROFILES),output_dir=self.output(),max_images=len(PROMPT_PROFILES),config=config(),client=client,context=context())
  self.assertEqual((result["network_calls"],result["editorial_calls"],result["r2_calls"]),(0,0,0));self.assertEqual(client.image_calls,0);self.assertEqual(client.editorial_calls,0);self.assertEqual(official.read_bytes(),b"official\n")
 def test_live_requires_both_flags_ci_is_forbidden_and_limit_is_enforced(self):
  ids=["baseline-v1"]
  for flags in ({"require_live":True},{"acknowledge_cost":True}):
   with self.assertRaisesRegex(EditorialError,"calibration_live_flags_required"):calibrate_images(date=context().date,profile_ids=ids,output_dir=self.output("flags"+str(len(flags))),max_images=1,config=config(api_key="x"),context=context(),**flags)
  with patch.dict(os.environ,{"CI":"true"}):
   with self.assertRaisesRegex(EditorialError,"calibration_live_forbidden_in_ci"):calibrate_images(date=context().date,profile_ids=ids,output_dir=self.output("ci"),max_images=1,require_live=True,acknowledge_cost=True,config=config(api_key="x"),context=context())
  with self.assertRaisesRegex(EditorialError,"calibration_image_limit"):calibrate_images(date=context().date,profile_ids=ids*2,output_dir=self.output("limit"),max_images=1,config=config(),context=context())
 def test_output_inside_git_and_symlink_are_rejected(self):
  with self.assertRaisesRegex(EditorialError,"calibration_output_inside_git"):calibrate_images(date=context().date,profile_ids=["baseline-v1"],output_dir=self.repo/"inside",max_images=1,config=config(),context=context())
  target=self.output("target");target.mkdir();link=self.output("link");link.symlink_to(target,True)
  with self.assertRaisesRegex(EditorialError,"calibration_output_symlink"):calibrate_images(date=context().date,profile_ids=["baseline-v1"],output_dir=link,max_images=1,config=config(),context=context())
 def test_live_uses_image_only_no_r2_and_persists_cost_hash_and_production_webp(self):
  client=ImageClient();out=self.output();tracked=[];real=tempfile.mkstemp
  def recording(*args,**kwargs):
   fd,path=real(*args,**kwargs)
   if kwargs.get("prefix",args[0] if args else "").startswith("tldr-calibration-provider-"):tracked.append(path)
   return fd,path
  with patch.dict(os.environ,{"CI":""}),patch("tools.tldr_editorial.calibration.tempfile.mkstemp",side_effect=recording),patch("tools.tldr_editorial.r2_storage.R2Storage",side_effect=AssertionError("R2 called")) as r2:
   result=calibrate_images(date=context().date,profile_ids=["print-graphic-v1"],output_dir=out,max_images=1,require_live=True,acknowledge_cost=True,config=config(api_key="x"),client=client,context=context())
  self.assertTrue(result["success"]);self.assertEqual((client.image_calls,client.editorial_calls),(1,0));self.assertEqual(result["r2_calls"],0);r2.assert_not_called();self.assertTrue(tracked);self.assertTrue(all(not Path(x).exists() for x in tracked))
  manifest=json.loads((out/"manifest.json").read_text());record=manifest["candidates"][0];self.assertEqual(record["usage"]["cost_usd"],0.125);data=(out/record["image_file"]).read_bytes();self.assertEqual(record["sha256"],"sha256:"+hashlib.sha256(data).hexdigest())
  raw,media=decode_image(png_value(),"image/png");source=self.output("source.raster");source.write_bytes(raw);expected=normalize_raster(source,media,config().max_provider_image_bytes,config().max_image_pixels,config().max_image_bytes);self.assertEqual(data,expected.data)
 def test_blind_gallery_hides_profiles_and_mapping_sets_match(self):
  out=self.output();calibrate_images(date=context().date,profile_ids=list(PROMPT_PROFILES),output_dir=out,max_images=len(PROMPT_PROFILES),config=config(),context=context())
  manifest=json.loads((out/"manifest.json").read_text());mapping=json.loads((out/"blind-map.json").read_text())["mapping"];gallery=(out/"gallery.html").read_text();score=json.loads((out/"score-template.json").read_text())
  candidate_ids={x["candidate_id"] for x in manifest["candidates"]};self.assertEqual(candidate_ids,set(mapping));self.assertEqual(candidate_ids,{x["candidate_id"] for x in score["scores"]})
  self.assertTrue(all(profile not in gallery for profile in PROMPT_PROFILES));self.assertTrue(all(x in gallery for x in candidate_ids));self.assertTrue(all(candidate().title in card for card in [gallery]));self.assertEqual((out/"blind-map.json").stat().st_mode&0o777,0o600)
 def test_failure_is_recorded_once_and_stops_paid_candidates(self):
  out=self.output();client=ImageClient(fail=True);ids=list(PROMPT_PROFILES)[:3]
  with patch.dict(os.environ,{"CI":""}):result=calibrate_images(date=context().date,profile_ids=ids,output_dir=out,max_images=3,require_live=True,acknowledge_cost=True,config=config(api_key="x"),client=client,context=context())
  self.assertFalse(result["success"]);self.assertEqual(client.image_calls,1);records=json.loads((out/"manifest.json").read_text())["candidates"];self.assertEqual(sum(x["status"]=="failed" for x in records),1);self.assertEqual(sum(x["status"]=="not_attempted" for x in records),2);self.assertNotIn("request_id",json.dumps(records))
 def test_custom_registered_shape_needs_no_engine_count_change(self):
  out=self.output();out.mkdir();custom=PromptProfile("future-v1","profile-999","Future profile preamble",SHARED_FACTUAL_RESTRICTIONS,())
  result=run_calibration(context=context(),profiles=[custom],output=out,cfg=config(),live=False);self.assertEqual(result["candidate_count"],1);self.assertEqual(result["network_calls"],0)

if __name__=="__main__":unittest.main()
