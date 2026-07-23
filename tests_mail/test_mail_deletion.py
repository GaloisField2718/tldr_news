from __future__ import annotations
import hashlib,imaplib,json,os,tempfile,unittest
from email.mime.text import MIMEText
from pathlib import Path
from unittest.mock import patch
from script import acknowledge,ingest,persist_normalized

NEWSLETTER_BODY=(
 "TLDR 2026-07-22\n\n"
 "NEWS\n\n"
 "A PUBLIC STORY (2 MINUTE READ)\n\n"
 "A public summary without private data.\n"
)

def _build_message(message_id="<mid-1@tldrnewsletter.com>",date_str="Wed, 22 Jul 2026 12:00:00 +0000"):
 msg=MIMEText(NEWSLETTER_BODY);msg["From"]="TLDR <dan@tldrnewsletter.com>";msg["Date"]=date_str;msg["Message-ID"]=message_id
 return msg.as_bytes()

class FakeIngestImap:
 """Fake IMAP server for ingest(): serves one FROM search result and its RFC822 bytes."""
 def __init__(self,uid_to_bytes:dict[str,bytes]):
  self.calls=[];self._data=uid_to_bytes
 def select(self,*a):self.calls.append(("select",a))
 def uid(self,*a):
  self.calls.append(("uid",a))
  if a[0]=="search":return "OK",[" ".join(self._data).encode()]
  if a[0]=="fetch":
   uid=a[1];raw=self._data[uid]
   return "OK",[(b"1 (RFC822 {%d}"%len(raw),raw)]
  return "OK",[]
 def close(self):pass
 def logout(self):pass

class FakeAckImap:
 """Fake IMAP server for acknowledge(): tracks per-UID presence, \\Deleted flags, and expunges."""
 def __init__(self,present_uids):
  self.calls=[];self.present=set(present_uids);self.flagged_deleted=set()
 def select(self,*a):self.calls.append(("select",a))
 def uid(self,*a):
  self.calls.append(("uid",a))
  cmd=a[0]
  if cmd=="SEARCH":
   target=a[2].split()[-1];found=target in self.present
   return "OK",[target.encode() if found else b""]
  if cmd=="STORE":
   uid=a[1]
   if len(a)>3 and "\\Deleted" in a[3]:self.flagged_deleted.add(uid)
   return "OK",[]
  if cmd=="EXPUNGE":
   uid=a[1]
   if uid in self.flagged_deleted:self.present.discard(uid)
   return "OK",[]
  return "OK",[]
 def expunge(self):
  self.calls.append(("expunge",()))
  for uid in list(self.flagged_deleted):self.present.discard(uid)
 def close(self):pass
 def logout(self):pass

class MailDeletionTests(unittest.TestCase):
 def setUp(self):
  self.old=Path.cwd();self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);os.chdir(self.root)
  self.state_path=self.root/"mail-pending.json";self.diag_path=self.root/"mail-deletions.json"
  self.env_patch=patch.dict(os.environ,{"TLDR_MAIL_STATE_PATH":str(self.state_path),"TLDR_MAIL_DIAGNOSTICS_PATH":str(self.diag_path)});self.env_patch.start()
 def tearDown(self):self.env_patch.stop();os.chdir(self.old);self.tmp.cleanup()

 def _pending_item(self,uid="42",message_id="<mid-1@tldrnewsletter.com>",normalized_ok=True):
  path=self.root/"TLDR"/"article.md";path.parent.mkdir(parents=True,exist_ok=True);path.write_text("safe newsletter body\n")
  item={"mailbox":"INBOX","uid":uid,"message_id":message_id,"source_path":str(path),"publication_date":"2026-07-22","source_sha256":"sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()}
  if normalized_ok:
   normalized=self.root/"generated"/"issues"/"tldr"/"2026"/"2026-07-22.json";normalized.parent.mkdir(parents=True,exist_ok=True);normalized.write_text('{"ok":true}')
   item["normalized_path"]=str(normalized);item["normalized_sha256"]="sha256:"+hashlib.sha256(normalized.read_bytes()).hexdigest()
  else:
   item["normalized_path"]=None;item["normalized_sha256"]=None
  return item

 def _write_state(self,items:dict):
  self.state_path.write_text(json.dumps({"schema_version":"1.0.0","pending":items}))

 # -- ingestion never deletes, and durably persists both raw and normalized data first --
 def test_ingest_persists_raw_and_normalized_before_any_pending_record(self):
  fake=FakeIngestImap({"42":_build_message()})
  with patch("script._connect",return_value=fake):self.assertEqual(ingest(),0)
  state=json.loads(self.state_path.read_text());self.assertEqual(len(state["pending"]),1)
  item=next(iter(state["pending"].values()))
  self.assertTrue(Path(item["source_path"]).is_file());self.assertTrue(Path(item["normalized_path"]).is_file())
  self.assertEqual("sha256:"+hashlib.sha256(Path(item["source_path"]).read_bytes()).hexdigest(),item["source_sha256"])
  self.assertEqual("sha256:"+hashlib.sha256(Path(item["normalized_path"]).read_bytes()).hexdigest(),item["normalized_sha256"])
  self.assertEqual(item["message_id"],"<mid-1@tldrnewsletter.com>");self.assertEqual(item["mailbox"],"INBOX");self.assertEqual(item["uid"],"42")
  # ingest() must never touch deletion machinery
  joined=repr(fake.calls);self.assertNotIn("STORE",joined);self.assertNotIn("EXPUNGE",joined);self.assertNotIn("Deleted",joined)

 # -- email is not deleted before raw durable persistence / before normalized persistence --
 def test_acknowledge_refuses_without_raw_source_on_disk(self):
  item=self._pending_item();Path(item["source_path"]).unlink()
  self._write_state({"k":item})
  with patch("script._connect",side_effect=AssertionError("must not connect when nothing is eligible")):
   self.assertEqual(acknowledge(),0)
  self.assertIn("k",json.loads(self.state_path.read_text())["pending"])

 def test_acknowledge_refuses_without_normalized_issue_data(self):
  item=self._pending_item(normalized_ok=False);self._write_state({"k":item})
  with patch("script._connect",side_effect=AssertionError("must not connect when nothing is eligible")):
   self.assertEqual(acknowledge(),0)
  self.assertIn("k",json.loads(self.state_path.read_text())["pending"])

 def test_acknowledge_refuses_when_normalized_hash_mismatches(self):
  item=self._pending_item();Path(item["normalized_path"]).write_text('{"tampered":true}')
  self._write_state({"k":item})
  with patch("script._connect",side_effect=AssertionError("must not connect when nothing is eligible")):
   self.assertEqual(acknowledge(),0)
  self.assertIn("k",json.loads(self.state_path.read_text())["pending"])

 # -- deletion after a verified durable local checkpoint --
 def test_acknowledge_permanently_deletes_after_verified_checkpoint(self):
  item=self._pending_item(uid="42");self._write_state({"k":item});fake=FakeAckImap({"42"})
  with patch("script._connect",return_value=fake):self.assertEqual(acknowledge(),0)
  self.assertEqual(json.loads(self.state_path.read_text())["pending"],{})
  self.assertNotIn("42",fake.present)
  joined=repr(fake.calls);self.assertIn("Deleted",joined);self.assertIn("EXPUNGE",joined);self.assertNotIn("X-GM-LABELS",joined)
  diagnostics=json.loads(self.diag_path.read_text())["deletions"]["k"]
  for field in ("mailbox","uid","message_id","source_path","source_sha256","normalized_path","normalized_sha256","deleted_at"):
   self.assertIn(field,diagnostics)
  self.assertEqual(diagnostics["uid"],"42");self.assertEqual(diagnostics["message_id"],"<mid-1@tldrnewsletter.com>")

 # -- publication failure after deletion remains fully recoverable from local state --
 def test_local_recovery_data_survives_after_deletion(self):
  item=self._pending_item(uid="42");self._write_state({"k":item});fake=FakeAckImap({"42"})
  with patch("script._connect",return_value=fake):self.assertEqual(acknowledge(),0)
  # Even though the email is gone, everything needed to resume publication is still local.
  self.assertTrue(Path(item["source_path"]).is_file());self.assertTrue(Path(item["normalized_path"]).is_file())
  self.assertTrue(self.diag_path.is_file())

 # -- retry does not process or delete the same message twice --
 def test_retry_after_success_is_a_pure_noop(self):
  item=self._pending_item(uid="42");self._write_state({"k":item});fake=FakeAckImap({"42"})
  with patch("script._connect",return_value=fake):self.assertEqual(acknowledge(),0)
  with patch("script._connect",side_effect=AssertionError("must not connect on an empty pending set")):
   self.assertEqual(acknowledge(),0)

 # -- deletion targets only the intended UID; unrelated messages are untouched --
 def test_deletion_targets_only_the_intended_uid(self):
  item=self._pending_item(uid="42");self._write_state({"k":item})
  fake=FakeAckImap({"42","99"})  # "99" is an unrelated message present in the mailbox
  with patch("script._connect",return_value=fake):self.assertEqual(acknowledge(),0)
  self.assertNotIn("42",fake.present);self.assertIn("99",fake.present)
  self.assertNotIn("99",fake.flagged_deleted)
  for call in fake.calls:
   if call[0]=="uid" and call[1][0] in ("STORE","EXPUNGE"):self.assertEqual(call[1][1],"42")

 # -- expunge (and \Deleted) is never issued before the checkpoint is verified --
 def test_expunge_not_called_before_checkpoint_completion(self):
  item=self._pending_item(normalized_ok=False);self._write_state({"k":item})
  calls=[]
  class Spy(FakeAckImap):
   def uid(self,*a):
    calls.append(a);return super().uid(*a)
  with patch("script._connect",return_value=Spy({"42"})):self.assertEqual(acknowledge(),0)
  self.assertEqual(calls,[])  # _connect() was never even reached

 # -- crash recovery: message already deleted server-side before local state was updated --
 def test_crash_recovery_when_message_already_gone_from_server(self):
  item=self._pending_item(uid="42");self._write_state({"k":item})
  fake=FakeAckImap(set())  # UID already absent, simulating a crash after a prior successful delete
  with patch("script._connect",return_value=fake):self.assertEqual(acknowledge(),0)
  self.assertEqual(json.loads(self.state_path.read_text())["pending"],{})
  joined=repr(fake.calls);self.assertNotIn("STORE",joined)  # never re-issues STORE for an already-gone message
  self.assertIn("k",json.loads(self.diag_path.read_text())["deletions"])

 # -- a hard failure mid-delete (e.g. dropped connection) does not corrupt local state --
 def test_store_failure_leaves_item_pending_for_retry(self):
  item=self._pending_item(uid="42")
  class FailingImap(FakeAckImap):
   def uid(self,*a):
    if a[0]=="STORE":self.calls.append(("uid",a));raise imaplib.IMAP4.error("connection reset")
    return super().uid(*a)
  self._write_state({"k":item});fake=FailingImap({"42"})
  with patch("script._connect",return_value=fake):self.assertEqual(acknowledge(),1)
  self.assertIn("k",json.loads(self.state_path.read_text())["pending"])  # still recoverable, not lost
  self.assertIn("42",fake.present)  # message was not actually deleted

if __name__=="__main__":unittest.main()
