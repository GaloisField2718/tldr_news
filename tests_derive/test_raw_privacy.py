from __future__ import annotations
import contextlib,hashlib,io,json,os,subprocess,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from tools.check_generated_consistency import check_generated
from tools.tldr_raw_privacy import RawPrivacyError,check_staged,inspect_raw_privacy,prepare_raw_source,sanitize_paths
from tools.tldr_derive.sanitizer import normalize_public_url
from script import acknowledge,persist_newsletter

OBSERVED="https://stratechery.com/2026/public-article/?access_token=DO_NOT_ECHO&utm_source=newsletter"

class RawPrivacyTests(unittest.TestCase):
 def setUp(self):
  self.old=Path.cwd();self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);os.chdir(self.root)
 def tearDown(self):os.chdir(self.old);self.tmp.cleanup()
 def git(self,*args):return subprocess.run(["git",*args],check=True,capture_output=True,text=True)
 def init_git(self):
  self.git("init","-b","main");self.git("config","user.email","raw-test@example.com");self.git("config","user.name","Raw Test")
 def stage(self,path="TLDR/article.md",text=OBSERVED):
  p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text+"\n");self.git("add","--",path);return p
 def check_output(self):
  err=io.StringIO()
  with contextlib.redirect_stderr(err):code=check_staged()
  return code,err.getvalue()
 def test_staged_index_catches_sensitive_parameter_without_value(self):
  self.init_git();self.stage();code,error=self.check_output();self.assertEqual(code,1);self.assertIn("host=stratechery.com",error);self.assertIn("key=access_token",error);self.assertNotIn("DO_NOT_ECHO",error);self.assertNotIn("https://",error)
 def test_scanner_reads_index_when_worktree_differs(self):
  self.init_git();p=self.stage();p.write_text("https://example.com/public?code=ok\n");code,error=self.check_output();self.assertEqual(code,1);self.assertIn("credential_query_parameter",error);self.assertNotIn("DO_NOT_ECHO",error)
 def test_paths_containing_spaces_are_nul_safe(self):
  self.init_git();self.stage("TLDR AI/article with spaces.md");code,error=self.check_output();self.assertEqual(code,1);self.assertIn("path=TLDR AI/article with spaces.md",error)
 def test_url_userinfo_rejected_without_password_in_error(self):
  finding=inspect_raw_privacy("https://user:DO_NOT_ECHO@example.com/article")[0];self.assertEqual(finding.category,"url_userinfo");self.assertNotIn("DO_NOT_ECHO",str(finding))
  with self.assertRaises(RawPrivacyError) as caught:prepare_raw_source("https://user:DO_NOT_ECHO@example.com/article")
  self.assertNotIn("DO_NOT_ECHO",str(caught.exception))
 def test_known_management_and_subscriber_urls_are_removed(self):
  source="Article\nhttps://tldr.tech/tech/manage?email=DO_NOT_ECHO\nhttps://refer.tldr.tech/private/path\n"
  clean,categories=prepare_raw_source(source);self.assertNotIn("DO_NOT_ECHO",clean);self.assertNotIn("refer.tldr.tech",clean);self.assertIn("subscriber_or_management_url",categories)
 def test_observed_host_key_is_canonicalized(self):
  clean,categories=prepare_raw_source(OBSERVED);self.assertEqual(clean,"https://stratechery.com/2026/public-article/?utm_source=newsletter\n");self.assertEqual(categories,["credential_parameter_removed"])
  encoded=OBSERVED.replace("&utm_source","&amp;utm_source");self.assertNotIn("access_token",prepare_raw_source(encoded)[0])
 def test_ordinary_and_ambiguous_public_parameters_remain(self):
  url="https://example.com/article?token=a&uid=b&user_id=c&key=d&code=e&utm_source=f"
  clean,_=prepare_raw_source(url);self.assertEqual(clean,url+"\n")
 def test_unknown_credential_url_is_rejected_not_redacted(self):
  with self.assertRaises(RawPrivacyError):prepare_raw_source("https://example.com/private?api_key=DO_NOT_ECHO")
 def test_whitespace_normalization_is_deterministic_and_idempotent(self):
  raw="Header  \r\n\r\nArticle\t\r\n\r\n\r\n";once,_=prepare_raw_source(raw);twice,_=prepare_raw_source(once);self.assertEqual(once,"Header\n\nArticle\n");self.assertEqual(once,twice)
 def test_mixed_leading_indentation_only_is_normalized(self):
  raw=" \ttext\n  \t \ttext\n\ttext\ntext \t value\ntrailing \t\n";clean,_=prepare_raw_source(raw)
  self.assertEqual(clean,"\ttext\n\t\ttext\n\ttext\ntext \t value\ntrailing\n");self.assertEqual(prepare_raw_source(clean)[0],clean)
 def test_explicit_sanitize_check_and_atomic_write(self):
  self.init_git();p=self.stage(text="Header  \n"+OBSERVED);before=p.read_bytes();out=io.StringIO()
  with contextlib.redirect_stdout(out):self.assertEqual(sanitize_paths([str(p)],check=True),1)
  self.assertEqual(p.read_bytes(),before);self.assertNotIn("DO_NOT_ECHO",out.getvalue())
  with contextlib.redirect_stdout(out):self.assertEqual(sanitize_paths([str(p)]),0)
  first=p.read_bytes()
  with contextlib.redirect_stdout(out):self.assertEqual(sanitize_paths([str(p)]),0)
  self.assertEqual(p.read_bytes(),first);self.assertIn(b"Header\n",first);self.assertNotIn("DO_NOT_ECHO",out.getvalue())
 def test_sanitize_repairs_index_for_git_diff_check(self):
  self.init_git();p=self.stage(text="# Header\n \titem\n  \t \titem\ntext \t value")
  self.assertEqual(sanitize_paths([str(p)],check=True),1);self.assertEqual(sanitize_paths([str(p)]),0);self.git("add","--",str(p.relative_to(self.root)))
  checked=subprocess.run(["git","diff","--cached","--check"],capture_output=True,text=True)
  self.assertEqual(checked.returncode,0,msg=checked.stdout+checked.stderr);self.assertNotIn("DO_NOT_ECHO",checked.stdout+checked.stderr)
 def test_sanitize_refuses_symlink(self):
  self.init_git();target=self.root/"target.md";target.write_text("safe\n");link=self.root/"TLDR"/"link.md";link.parent.mkdir();link.symlink_to(target)
  err=io.StringIO()
  with contextlib.redirect_stderr(err):self.assertEqual(sanitize_paths([str(link)]),1)
  self.assertIn("path_outside_approved_sources",err.getvalue())
 class FakeImap:
  def __init__(self):self.calls=[]
  def store(self,*args):self.calls.append(("store",args))
  def expunge(self):self.calls.append(("expunge",()))
 def test_successful_ingestion_persists_without_acknowledging_message(self):
  fake=self.FakeImap();path=Path("TLDR/article.md");self.assertTrue(persist_newsletter(fake,"42",path,"public newsletter\n"));self.assertTrue(path.exists());self.assertEqual(fake.calls,[])
  self.assertTrue(persist_newsletter(fake,"42",path,"public newsletter\n"));self.assertEqual(fake.calls,[])
  self.assertFalse(persist_newsletter(fake,"43",path,"different newsletter\n"));self.assertEqual(path.read_text(),"public newsletter\n")
 def test_acknowledgement_requires_durable_origin_and_archives_without_delete(self):
  path=Path("TLDR/article.md");path.parent.mkdir();path.write_text("safe\n");state_path=self.root/"pending.json";state={"schema_version":"1.0.0","pending":{"key":{"uid":"42","source_path":str(path),"publication_date":"2026-07-22","source_sha256":"sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()}}};state_path.write_text(json.dumps(state))
  class AckImap:
   def __init__(self):self.calls=[]
   def select(self,*a):self.calls.append(("select",a))
   def create(self,*a):self.calls.append(("create",a));return "OK",[]
   def uid(self,*a):self.calls.append(("uid",a));return "OK",[]
   def close(self):pass
   def logout(self):pass
  fake=AckImap()
  with patch.dict(os.environ,{"TLDR_MAIL_STATE_PATH":str(state_path)}),patch("script._tracked_at_origin",return_value=True),patch("script._connect",return_value=fake):self.assertEqual(acknowledge(),0)
  self.assertEqual(json.loads(state_path.read_text())["pending"],{});joined=repr(fake.calls);self.assertIn("TLDR-Processed",joined);self.assertIn("-X-GM-LABELS",joined);self.assertNotIn("Deleted",joined);self.assertNotIn("expunge",joined)
 def test_unsafe_ingestion_does_not_write_or_delete_message(self):
  fake=self.FakeImap();path=Path("TLDR/article.md");out=io.StringIO()
  with contextlib.redirect_stdout(out):written=persist_newsletter(fake,"42",path,"https://example.com/private?client_secret=DO_NOT_ECHO")
  self.assertFalse(written);self.assertFalse(path.exists());self.assertEqual(fake.calls,[]);self.assertNotIn("DO_NOT_ECHO",out.getvalue());self.assertNotIn("https://",out.getvalue())
 def test_normalized_url_policy_canonicalizes_observed_and_rejects_unknown_credentials(self):
  self.assertEqual(normalize_public_url(OBSERVED),"https://stratechery.com/2026/public-article/?utm_source=newsletter")
  self.assertIsNone(normalize_public_url("https://example.com/private?api_key=DO_NOT_ECHO"))
  self.assertEqual(normalize_public_url("https://example.com/public?token=a&uid=b&user_id=c&key=d&code=e"),"https://example.com/public?token=a&uid=b&user_id=c&key=d&code=e")
 def test_normalized_derivation_after_sanitation_is_consistent(self):
  source=self.root/"TLDR"/"article_01-01-2024.md";source.parent.mkdir();raw="# Articles TLDR 01-01-2024\n\nTLDR 2024-01-01\n\nNEWS\n\nPUBLIC STORY (2 MINUTE READ) [1]\n\nA public summary.\n\nLinks:\n------\n[1] "+OBSERVED+"\n";source.write_text(prepare_raw_source(raw)[0])
  repo=Path(__file__).resolve().parents[1];env={**os.environ,"PYTHONPATH":str(repo)}
  run=subprocess.run([os.sys.executable,"-m","tools.tldr_derive","--repo-root",str(self.root),"--output",str(self.root/"generated"),"generate","--all"],env=env,capture_output=True,text=True)
  self.assertEqual(run.returncode,0,msg=run.stderr);self.assertEqual(check_generated(self.root/"generated"),[]);self.assertNotIn("access_token",source.read_text());self.assertTrue(all("access_token" not in p.read_text() for p in (self.root/"generated").rglob("*.json")))

if __name__=="__main__":unittest.main()
