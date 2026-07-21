from __future__ import annotations
import hashlib,json,os,subprocess,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from tools.tldr_editorial.core import EditorialError
from tools.tldr_editorial.generator import generate
from tests_editorial.helpers import config,write_generated
from tests_editorial.test_generator_artifacts import Live,Storage

class NeverExternal:
 def __init__(self):self.calls=0
 def editorial(self,*a,**k):self.calls+=1;raise AssertionError("OpenRouter called")
 def image(self,*a,**k):self.calls+=1;raise AssertionError("OpenRouter called")
 def build_public_url(self,*a,**k):self.calls+=1;raise AssertionError("R2 called")
 def ensure_uploaded(self,*a,**k):self.calls+=1;raise AssertionError("R2 called")

class LiveNoopWorkspaceTests(unittest.TestCase):
 def setUp(self):
  self.ci_patcher=patch.dict(os.environ,{"CI":""});self.ci_patcher.start()
  self.old=Path.cwd();self.tmp=tempfile.TemporaryDirectory();self.repo=Path(self.tmp.name);os.chdir(self.repo)
  self.g=self.repo/"generated";self.o=self.g/"editorial";write_generated(self.g)
  generate(generated=self.g,output=self.o,latest=True,config=config())
  (self.repo/"tracked.txt").write_text("clean\n")
  self.git("init","-b","main");self.git("config","user.email","editorial-test@example.com");self.git("config","user.name","Editorial Test");self.git("add","-A");self.git("commit","-m","fixture")
  self.live_config=config(enabled=True,api_key="test-key")
 def tearDown(self):
  try:os.chdir(self.old);self.tmp.cleanup()
  finally:self.ci_patcher.stop()
 def git(self,*args,check=True):return subprocess.run(["git",*args],check=check,capture_output=True,text=True)
 def first_live(self,output=None):
  return generate(generated=self.g,output=output or self.o,latest=True,require_live=True,config=self.live_config,client=Live(),storage=Storage())
 def reject(self,**kwargs):
  spy=NeverExternal()
  with self.assertRaises(EditorialError):generate(generated=self.g,output=self.o,latest=True,require_live=True,config=self.live_config,client=spy,storage=spy,**kwargs)
  self.assertEqual(spy.calls,0)
 def expected_paths(self):return self.o/"2026"/"2026-07-21.json",self.o/"manifest.json"
 def test_first_require_live_generation_requires_fully_clean_repository(self):
  (self.repo/"tracked.txt").write_text("dirty\n");self.reject()
  self.assertEqual(json.loads((self.o/"2026"/"2026-07-21.json").read_text())["status"],"disabled")
 def test_second_require_live_accepts_exact_pending_json_and_preserves_every_byte_and_mtime(self):
  first=self.first_live();self.assertEqual(first["status"],"ai_complete");artifact,manifest=self.expected_paths()
  status=self.git("status","--porcelain=v1").stdout.splitlines();self.assertEqual({x[3:] for x in status},{str(artifact.relative_to(self.repo)),str(manifest.relative_to(self.repo))})
  before=[(p.read_bytes(),hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in (artifact,manifest)];time.sleep(.01)
  spy=NeverExternal();second=generate(generated=self.g,output=self.o,latest=True,require_live=True,config=self.live_config,client=spy,storage=spy)
  after=[(p.read_bytes(),hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in (artifact,manifest)]
  self.assertEqual(second|{"dossier_bytes":second["dossier_bytes"]},{"date":"2026-07-21","status":"ai_complete","written":False,"network_calls":0,"r2_calls":0,"dossier_bytes":second["dossier_bytes"],"noop":True});self.assertEqual(spy.calls,0);self.assertEqual(before,after)
 def test_custom_output_is_resolved_dynamically(self):
  custom=self.repo/"custom"/"editorial";generate(generated=self.g,output=custom,latest=True,config=config());self.git("add","custom");self.git("commit","-m","custom disabled")
  generate(generated=self.g,output=custom,latest=True,require_live=True,config=self.live_config,client=Live(),storage=Storage())
  spy=NeverExternal();r=generate(generated=self.g,output=custom,latest=True,require_live=True,config=self.live_config,client=spy,storage=spy);self.assertTrue(r["noop"]);self.assertEqual(spy.calls,0)
 def test_untracked_new_dated_artifact_and_modified_manifest_are_accepted(self):
  # Add a second normalized date while retaining the first date in its manifest.
  old=json.loads((self.g/"manifest.json").read_text());write_generated(self.g,"2026-07-22");new=json.loads((self.g/"manifest.json").read_text());(self.g/"manifest.json").write_text(json.dumps({**new,"issues":old["issues"]+new["issues"]}))
  self.git("add","generated");self.git("commit","-m","second normalized date")
  generate(generated=self.g,output=self.o,date="2026-07-22",require_live=True,config=self.live_config,client=Live(),storage=Storage())
  artifact=self.o/"2026"/"2026-07-22.json";states={x[3:]:x[:2] for x in self.git("status","--porcelain=v1").stdout.splitlines()};self.assertEqual(states[str(artifact.relative_to(self.repo))],"??");self.assertEqual(states[str((self.o/"manifest.json").relative_to(self.repo))]," M")
  spy=NeverExternal();r=generate(generated=self.g,output=self.o,date="2026-07-22",require_live=True,config=self.live_config,client=spy,storage=spy);self.assertTrue(r["noop"]);self.assertEqual(spy.calls,0)
 def test_unrelated_modified_tracked_file_rejected(self):self.first_live();(self.repo/"tracked.txt").write_text("dirty\n");self.reject()
 def test_unrelated_untracked_file_with_spaces_rejected(self):self.first_live();(self.repo/"unrelated file.txt").write_text("dirty\n");self.reject()
 def test_staged_artifact_or_manifest_rejected(self):
  for which in (0,1):
   with self.subTest(which=which):
    if which:self.tearDown();self.setUp()
    self.first_live();self.git("add",str(self.expected_paths()[which]));self.reject()
 def test_deleted_or_renamed_expected_artifact_rejected(self):
  for rename in (False,True):
   with self.subTest(rename=rename):
    if rename:self.tearDown();self.setUp()
    self.first_live();artifact,_=self.expected_paths()
    if rename:artifact.rename(artifact.with_name("renamed.json"))
    else:artifact.unlink()
    self.reject()
 def test_conflicted_expected_artifact_rejected(self):
  self.first_live();self.git("add","generated/editorial");self.git("commit","-m","ready");artifact,_=self.expected_paths();self.git("checkout","-b","other");artifact.write_text(artifact.read_text()+"other\n");self.git("add",str(artifact));self.git("commit","-m","other");self.git("checkout","main");artifact.write_text(artifact.read_text()+"main\n");self.git("add",str(artifact));self.git("commit","-m","main");self.git("merge","other",check=False);self.assertIn("UU",self.git("status","--porcelain=v1").stdout);self.reject()
 def test_editorial_temporary_file_rejected(self):self.first_live();(self.o/".tldr-editorial-left.tmp").write_text("x");self.reject()
 def test_symlinked_expected_artifact_rejected(self):
  self.first_live();artifact,_=self.expected_paths();target=artifact.with_name("target.json");artifact.rename(target);artifact.symlink_to(target.name);self.reject()
 def test_malformed_or_inconsistent_contract_rejected(self):
  for malformed in (True,False):
   with self.subTest(malformed=malformed):
    if not malformed:self.tearDown();self.setUp()
    self.first_live();artifact,manifest=self.expected_paths()
    if malformed:artifact.write_text("{bad")
    else:
     doc=json.loads(manifest.read_text());doc["dates"][-1]["bytes"]+=1;manifest.write_text(json.dumps(doc,sort_keys=True,separators=(",",":"))+"\n")
    self.reject()
 def test_changed_normalized_source_rejects_before_external_call(self):
  self.first_live();issue=next((self.g/"issues").rglob("*.json"));doc=json.loads(issue.read_text());doc["sections"][0]["articles"][0]["summary"]+=" changed";issue.write_text(json.dumps(doc));self.reject()
 def test_force_and_retry_image_require_fully_clean_workspace(self):
  for flag in ("force","retry_image"):
   with self.subTest(flag=flag):
    if flag=="retry_image":self.tearDown();self.setUp()
    self.first_live();self.reject(**{flag:True})
 def test_public_base_update_requires_fully_clean_workspace(self):
  self.first_live();spy=NeverExternal();changed=config(**{**self.live_config.__dict__,"r2_public_base_url":"https://new-assets.example.workers.dev"})
  with self.assertRaises(EditorialError):generate(generated=self.g,output=self.o,latest=True,require_live=True,config=changed,client=spy,storage=spy)
  self.assertEqual(spy.calls,0)
 def test_ci_remains_forbidden(self):
  spy=NeverExternal()
  with patch.dict(os.environ,{"CI":"true"}):
   with self.assertRaisesRegex(EditorialError,"live_generation_forbidden_in_ci"):generate(generated=self.g,output=self.o,latest=True,require_live=True,config=self.live_config,client=spy,storage=spy)
  self.assertEqual(spy.calls,0)

if __name__=="__main__":unittest.main()
