from __future__ import annotations
import base64,hashlib,io,json,os,subprocess,tempfile,unittest
from dataclasses import FrozenInstanceError,replace
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from tools.tldr_editorial.calibration import AMD_ANTI_DEFAULT_CLAUSE,CalibrationContext,assemble_experimental_prompt,assemble_story_prompt,calibrate_images,calibrate_story_images,parse_combinations,read_blind_mapping,run_calibration
from tools.tldr_editorial.cli import main as cli_main
from tools.tldr_editorial.candidates import Candidate
from tools.tldr_editorial.core import EditorialError
from tools.tldr_editorial.image import assemble_prompt,decode_image,normalize_raster
from tools.tldr_editorial.calibration_stories import STORIES,resolve_story
from tools.tldr_editorial.illustration_concepts import CONCEPT_PROFILES,ConceptProfile
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

def candidate():return Candidate("c001","tldr:2026-07-21","tldr:2026-07-21:a09","tldr","NEWS","AMD Helios rack system","AMD introduced a rack-scale AI system with physically integrated compute and networking.","https://example.com/story","example.com",3,"editorial",(0,0))
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
 def test_style_and_concept_registries_are_independent_and_declarative(self):
  self.assertTrue(CONCEPT_PROFILES);self.assertTrue(PROMPT_PROFILES);self.assertFalse(set(CONCEPT_PROFILES)&set(PROMPT_PROFILES));self.assertEqual(len(CONCEPT_PROFILES),len(set(CONCEPT_PROFILES)))
  concept_fields=set(ConceptProfile.__dataclass_fields__);style_fields=set(PromptProfile.__dataclass_fields__)
  self.assertFalse(concept_fields&{"rendering_style","medium","palette","lighting","material_treatment"});self.assertFalse(style_fields&{"central_subject_override","visual_metaphor_override","composition_override","factual_rationale","required_source_references"})
  style_text=" ".join(x.preamble for x in PROMPT_PROFILES.values()).lower();self.assertTrue(all(term not in style_text for term in ("amd","helios","microsoft","nvidia")))
 def test_experimental_prompt_is_deterministic_replaces_concept_and_keeps_exact_facts(self):
  concept=CONCEPT_PROFILES["integrated-stack-v1"];style=PROMPT_PROFILES["print-graphic-v1"];original=json.loads(json.dumps(context().brief));prompt=assemble_experimental_prompt(context(),style,concept)
  self.assertEqual(prompt,assemble_experimental_prompt(context(),style,concept));self.assertIn(candidate().title,prompt);self.assertIn(candidate().summary,prompt);self.assertIn(concept.central_subject_override,prompt);self.assertIn(AMD_ANTI_DEFAULT_CLAUSE,prompt);self.assertNotIn(original["central_subject"],prompt);self.assertEqual(context().brief,original)
 def test_dry_default_has_zero_calls_and_never_writes_official_artifacts(self):
  official=self.repo/"generated/editorial/manifest.json";official.parent.mkdir(parents=True);official.write_bytes(b"official\n");subprocess.run(["git","add","generated"],check=True);subprocess.run(["git","commit","-m","official"],check=True,capture_output=True)
  client=ImageClient();result=calibrate_images(date=context().date,profile_ids=list(PROMPT_PROFILES),output_dir=self.output(),max_images=len(PROMPT_PROFILES),config=config(),client=client,context=context())
  self.assertEqual((result["network_calls"],result["editorial_calls"],result["r2_calls"]),(0,0,0));self.assertEqual(client.image_calls,0);self.assertEqual(client.editorial_calls,0);self.assertEqual(official.read_bytes(),b"official\n")
 def test_default_one_sample_per_profile(self):
  out=self.output();selected=list(PROMPT_PROFILES)[:2];result=calibrate_images(date=context().date,profile_ids=selected,output_dir=out,max_images=2,config=config(),context=context())
  mapping=json.loads((out/"blind-map.json").read_text())["mapping"];self.assertEqual(result["candidate_count"],2);self.assertEqual({x["sample_index"] for x in mapping.values()},{1});self.assertEqual({x["style_profile_id"] for x in mapping.values()},set(selected));self.assertEqual({x["concept_profile_id"] for x in mapping.values()},{"official-visual-brief"})
 def test_two_samples_are_anonymous_complete_and_use_identical_profile_prompts(self):
  out=self.output();selected=list(PROMPT_PROFILES)[:2];client=ImageClient();result=calibrate_images(date=context().date,profile_ids=selected,output_dir=out,max_images=4,samples_per_profile=2,config=config(),client=client,context=context())
  manifest=json.loads((out/"manifest.json").read_text());mapping=json.loads((out/"blind-map.json").read_text())["mapping"];gallery=(out/"gallery.html").read_text();ids=[x["candidate_id"] for x in manifest["candidates"]]
  self.assertEqual(result["candidate_count"],4);self.assertEqual(len(ids),len(set(ids)));self.assertEqual(set(ids),set(mapping));self.assertEqual(client.image_calls,0)
  for profile_id in selected:
   members={candidate_id for candidate_id,value in mapping.items() if value["style_profile_id"]==profile_id}
   self.assertEqual(len(members),2);self.assertEqual(len({x["prompt_sha256"] for x in manifest["candidates"] if x["candidate_id"] in members}),1)
  self.assertTrue(all(profile_id not in gallery and profile_id not in (out/"manifest.json").read_text() for profile_id in selected));self.assertNotIn("sample_index",gallery);self.assertNotIn("sample_index",(out/"manifest.json").read_text())
 def test_cartesian_concept_count_hash_relationships_blindness_and_maximum(self):
  official=self.repo/"generated/editorial/manifest.json";official.parent.mkdir(parents=True);official.write_bytes(b"official\n");subprocess.run(["git","add","generated"],check=True);subprocess.run(["git","commit","-m","official"],check=True,capture_output=True)
  out=self.output();styles=list(PROMPT_PROFILES)[:2];concepts=list(CONCEPT_PROFILES)[:3];client=ImageClient();result=calibrate_images(date=context().date,profile_ids=styles,concept_ids=concepts,output_dir=out,max_images=12,samples_per_combination=2,config=config(),client=client,context=context());self.assertEqual(official.read_bytes(),b"official\n")
  self.assertEqual(result["candidate_count"],12);self.assertEqual((result["network_calls"],result["editorial_calls"],result["r2_calls"]),(0,0,0));self.assertEqual((client.image_calls,client.editorial_calls),(0,0))
  manifest=json.loads((out/"manifest.json").read_text());mapping=json.loads((out/"blind-map.json").read_text())["mapping"];gallery=(out/"gallery.html").read_text();manifest_text=(out/"manifest.json").read_text();by={x["candidate_id"]:x for x in manifest["candidates"]}
  self.assertEqual(set(mapping),set(by));self.assertTrue(all(set(v)=={"style_profile_id","concept_profile_id","sample_index"} for v in mapping.values()))
  hashes={(s,c):{by[cid]["prompt_sha256"] for cid,v in mapping.items() if v["style_profile_id"]==s and v["concept_profile_id"]==c} for s in styles for c in concepts}
  self.assertTrue(all(len(value)==1 for value in hashes.values()));self.assertNotEqual(hashes[(styles[0],concepts[0])],hashes[(styles[0],concepts[1])]);self.assertNotEqual(hashes[(styles[0],concepts[0])],hashes[(styles[1],concepts[0])])
  self.assertTrue(all(x.get("original_visual_brief_sha256") and x.get("experimental_concept_sha256") for x in by.values()));self.assertTrue(all(value not in gallery and value not in manifest_text for value in styles+concepts));self.assertNotIn("sample_index",gallery);self.assertNotIn("sample_index",manifest_text)
  self.assertEqual(gallery.count(candidate().title),1);self.assertEqual(gallery.count(candidate().summary),1);self.assertIn("grid-template-columns:repeat(3",gallery);self.assertIn("<dialog",gallery)
  with self.assertRaisesRegex(EditorialError,"calibration_image_limit"):calibrate_images(date=context().date,profile_ids=styles,concept_ids=concepts,output_dir=self.output("too-many"),max_images=11,samples_per_combination=2,config=config(),context=context())
 def test_three_explicit_pairs_with_two_samples_are_complete_blind_and_zero_call(self):
  pairs=[("print-graphic-v1","integrated-stack-v1"),("constructed-collage-v1","integrated-stack-v1"),("print-graphic-v1","challenger-enters-v1")];out=self.output();client=ImageClient();result=calibrate_images(date=context().date,combinations=pairs,output_dir=out,max_images=6,samples_per_combination=2,config=config(),client=client,context=context())
  self.assertEqual(result["candidate_count"],6);self.assertEqual((result["network_calls"],result["editorial_calls"],result["r2_calls"]),(0,0,0));self.assertEqual((client.image_calls,client.editorial_calls),(0,0))
  manifest=json.loads((out/"manifest.json").read_text());manifest_text=(out/"manifest.json").read_text();mapping=json.loads((out/"blind-map.json").read_text())["mapping"];gallery=(out/"gallery.html").read_text();records={x["candidate_id"]:x for x in manifest["candidates"]}
  self.assertEqual(set(records),set(mapping));self.assertTrue(all(set(value)=={"style_profile_id","concept_profile_id","sample_index"} for value in mapping.values()));self.assertEqual({(v["style_profile_id"],v["concept_profile_id"]) for v in mapping.values()},set(pairs))
  hashes=[]
  for pair in pairs:
   members=[candidate_id for candidate_id,value in mapping.items() if (value["style_profile_id"],value["concept_profile_id"])==pair];self.assertEqual({mapping[x]["sample_index"] for x in members},{1,2});pair_hashes={records[x]["prompt_sha256"] for x in members};self.assertEqual(len(pair_hashes),1);hashes.extend(pair_hashes)
  self.assertEqual(len(set(hashes)),3);self.assertTrue(all(candidate().title in gallery and candidate().summary in gallery for _ in [0]));self.assertTrue(all(token not in gallery and token not in manifest_text for pair in pairs for token in pair));self.assertNotIn("sample_index",gallery);self.assertNotIn("sample_index",manifest_text)
 def test_explicit_pair_validation_conflicts_and_limit(self):
  valid=[("print-graphic-v1","integrated-stack-v1")]
  for value in ("","print-graphic-v1","print-graphic-v1:",":integrated-stack-v1","a:b:c","a:b,"):
   with self.assertRaises(EditorialError):parse_combinations(value)
  with self.assertRaisesRegex(EditorialError,"calibration_combinations_required"):calibrate_images(date=context().date,combinations=[],output_dir=self.output("empty-pairs"),max_images=1,config=config(),context=context())
  with self.assertRaisesRegex(EditorialError,"calibration_combination_malformed"):calibrate_images(date=context().date,combinations=[("print-graphic-v1",)],output_dir=self.output("malformed-pair"),max_images=1,config=config(),context=context())
  with self.assertRaisesRegex(EditorialError,"calibration_duplicate_combination"):calibrate_images(date=context().date,combinations=valid*2,output_dir=self.output("dup-pair"),max_images=2,config=config(),context=context())
  with self.assertRaisesRegex(EditorialError,"calibration_combination_style_unknown"):calibrate_images(date=context().date,combinations=[("missing-style","integrated-stack-v1")],output_dir=self.output("style-unknown"),max_images=1,config=config(),context=context())
  with self.assertRaisesRegex(EditorialError,"calibration_combination_concept_unknown"):calibrate_images(date=context().date,combinations=[("print-graphic-v1","missing-concept")],output_dir=self.output("concept-unknown"),max_images=1,config=config(),context=context())
  with self.assertRaisesRegex(EditorialError,"calibration_combination_mode_conflict"):calibrate_images(date=context().date,profile_ids=["print-graphic-v1"],combinations=valid,output_dir=self.output("style-conflict"),max_images=1,config=config(),context=context())
  with self.assertRaisesRegex(EditorialError,"calibration_combination_mode_conflict"):calibrate_images(date=context().date,concept_ids=["integrated-stack-v1"],combinations=valid,output_dir=self.output("concept-conflict"),max_images=1,config=config(),context=context())
  with self.assertRaisesRegex(EditorialError,"calibration_image_limit"):calibrate_images(date=context().date,combinations=valid*1+[('constructed-collage-v1','integrated-stack-v1')],output_dir=self.output("pair-limit"),max_images=3,samples_per_combination=2,config=config(),context=context())
  with patch("sys.stderr",new=io.StringIO()):self.assertEqual(cli_main(["calibrate-images","--date",context().date,"--profiles","print-graphic-v1","--concepts","integrated-stack-v1","--output-dir",str(self.output("legacy-conflict")),"--max-images","1"]),2)
 def test_registered_calibration_stories_resolve_exactly_and_detect_drift(self):
  generated=Path(__file__).resolve().parents[1]/"generated";self.assertEqual(set(STORIES),{"secure-agent-sandboxes-v1","workers-automation-threshold-v1"})
  for story in STORIES.values():
   source=resolve_story(story,generated);self.assertEqual((source.issue_id,source.article_id),(story.issue_id,story.article_id));self.assertEqual(source.title,story.expected_title);self.assertIn(source.summary,assemble_story_prompt(story,source,PROMPT_PROFILES["print-graphic-v1"]))
  with self.assertRaisesRegex(EditorialError,"calibration_story_title_drift"):resolve_story(replace(next(iter(STORIES.values())),expected_title="drift"),generated)
  with self.assertRaisesRegex(EditorialError,"calibration_story_summary_drift"):resolve_story(replace(next(iter(STORIES.values())),expected_summary_sha256="sha256:deadbeef"),generated)
 def test_story_combinations_are_grouped_blind_complete_and_zero_network(self):
  pairs=[("secure-agent-sandboxes-v1","constructed-collage-v1"),("secure-agent-sandboxes-v1","print-graphic-v1"),("workers-automation-threshold-v1","constructed-collage-v1"),("workers-automation-threshold-v1","print-graphic-v1")];out=self.output();client=ImageClient();generated=Path(__file__).resolve().parents[1]/"generated";result=calibrate_story_images(story_combinations=pairs,output_dir=out,max_images=4,generated=generated,config=config(),client=client)
  self.assertEqual(result["candidate_count"],4);self.assertEqual((result["network_calls"],result["editorial_calls"],result["r2_calls"]),(0,0,0));self.assertEqual((client.image_calls,client.editorial_calls),(0,0));manifest=json.loads((out/"manifest.json").read_text());mapping=json.loads((out/"blind-map.json").read_text())["mapping"];gallery=(out/"gallery.html").read_text();public=gallery+(out/"manifest.json").read_text();records=[x for group in manifest["story_groups"] for x in group["candidates"]]
  self.assertEqual(set(mapping),{x["candidate_id"] for x in records});self.assertTrue(all(set(x)=={"story_id","style_profile_id","sample_index"} for x in mapping.values()));self.assertEqual({(x["story_id"],x["style_profile_id"]) for x in mapping.values()},set(pairs));self.assertEqual(len(manifest["story_groups"]),2);self.assertTrue(all(len(x["candidates"])==2 for x in manifest["story_groups"]));self.assertIn("Story A",gallery);self.assertIn("Story B",gallery);self.assertIn("grid-template-columns:repeat(2",gallery);self.assertTrue(all(token not in public for pair in pairs for token in pair));self.assertNotIn("sample_index",public);self.assertFalse(list(out.glob("*.webp")))
  hashes={(v["story_id"],v["style_profile_id"]):next(x["prompt_sha256"] for x in records if x["candidate_id"]==cid) for cid,v in mapping.items()};self.assertNotEqual(hashes[pairs[0]],hashes[pairs[1]]);self.assertNotEqual(hashes[pairs[0]],hashes[pairs[2]])
  with self.assertRaisesRegex(EditorialError,"calibration_duplicate_story_combination"):calibrate_story_images(story_combinations=pairs[:1]*2,output_dir=self.output("story-dup"),max_images=2,generated=generated,config=config())
  with self.assertRaisesRegex(EditorialError,"calibration_image_limit"):calibrate_story_images(story_combinations=pairs,output_dir=self.output("story-limit"),max_images=3,generated=generated,config=config())
 def test_live_requires_both_flags_ci_is_forbidden_and_limit_is_enforced(self):
  ids=["baseline-v1"]
  for flags in ({"require_live":True},{"acknowledge_cost":True}):
   with self.assertRaisesRegex(EditorialError,"calibration_live_flags_required"):calibrate_images(date=context().date,profile_ids=ids,output_dir=self.output("flags"+str(len(flags))),max_images=1,config=config(api_key="x"),context=context(),**flags)
  with patch.dict(os.environ,{"CI":"true"}):
   with self.assertRaisesRegex(EditorialError,"calibration_live_forbidden_in_ci"):calibrate_images(date=context().date,profile_ids=ids,output_dir=self.output("ci"),max_images=1,require_live=True,acknowledge_cost=True,config=config(api_key="x"),context=context())
  with self.assertRaisesRegex(EditorialError,"calibration_image_limit"):calibrate_images(date=context().date,profile_ids=["baseline-v1","print-graphic-v1"],output_dir=self.output("limit"),max_images=3,samples_per_profile=2,config=config(),context=context())
  with self.assertRaisesRegex(EditorialError,"calibration_duplicate_profile"):calibrate_images(date=context().date,profile_ids=ids*2,output_dir=self.output("duplicate"),max_images=2,config=config(),context=context())
  for value in (0,6):
   with self.assertRaisesRegex(EditorialError,"calibration_samples_per_profile_invalid"):calibrate_images(date=context().date,profile_ids=ids,output_dir=self.output("samples"+str(value)),max_images=10,samples_per_profile=value,config=config(),context=context())
  for value in (0,4):
   with self.assertRaisesRegex(EditorialError,"calibration_samples_per_combination_invalid"):calibrate_images(date=context().date,profile_ids=ids,concept_ids=["integrated-stack-v1"],output_dir=self.output("combinations"+str(value)),max_images=10,samples_per_combination=value,config=config(),context=context())
  with self.assertRaisesRegex(EditorialError,"calibration_duplicate_concept"):calibrate_images(date=context().date,profile_ids=ids,concept_ids=["integrated-stack-v1"]*2,output_dir=self.output("duplicate-concept"),max_images=2,config=config(),context=context())
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
   result=calibrate_images(date=context().date,profile_ids=["print-graphic-v1"],concept_ids=["integrated-stack-v1"],output_dir=out,max_images=1,require_live=True,acknowledge_cost=True,config=config(api_key="x"),client=client,context=context())
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
  with patch.dict(os.environ,{"CI":""}):result=calibrate_images(date=context().date,profile_ids=ids,output_dir=out,max_images=6,samples_per_profile=2,require_live=True,acknowledge_cost=True,config=config(api_key="x"),client=client,context=context())
  self.assertFalse(result["success"]);self.assertEqual(client.image_calls,1);records=json.loads((out/"manifest.json").read_text())["candidates"];self.assertEqual(sum(x["status"]=="failed" for x in records),1);self.assertEqual(sum(x["status"]=="not_attempted" for x in records),5);self.assertNotIn("request_id",json.dumps(records))
 def test_existing_round_one_private_mapping_remains_readable(self):
  path=self.output("old-map.json");path.write_text(json.dumps({"mapping":{"candidate-old":{"profile_id":"print-graphic-v1","sample_index":2}}}));value=read_blind_mapping(path)
  self.assertEqual(value,{"candidate-old":{"style_profile_id":"print-graphic-v1","concept_profile_id":"official-visual-brief","sample_index":2}})
 def test_custom_registered_shape_needs_no_engine_count_change(self):
  out=self.output();out.mkdir();custom=PromptProfile("future-v1","profile-999","Future profile preamble",SHARED_FACTUAL_RESTRICTIONS,())
  result=run_calibration(context=context(),profiles=[custom],output=out,cfg=config(),live=False);self.assertEqual(result["candidate_count"],1);self.assertEqual(result["network_calls"],0)

if __name__=="__main__":unittest.main()
