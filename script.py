"""Fetch TLDR newsletters durably; permanently delete mail only after a verified local checkpoint."""
from __future__ import annotations
import argparse,email,hashlib,imaplib,json,os,quopri,re,tempfile,time
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values
from tools.tldr_raw_privacy import RawPrivacyError,format_finding,is_approved_source,prepare_raw_source
from tools.tldr_derive.discovery import resolve_source
from tools.tldr_derive.parser import parse_source
from tools.tldr_derive.writer import validate_output_root,write_issue

STATE_VERSION="1.0.0";DEFAULT_STATE=Path.home()/".local/state/tldr_news/mail-pending.json"
DEFAULT_DIAGNOSTICS=Path.home()/".local/state/tldr_news/mail-deletions.json"
MAILBOX="INBOX"
def _atomic_write(path:Path,text:str,mode:int=0o644)->None:
 path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix=".tldr-",dir=path.parent)
 try:
  with os.fdopen(fd,"w",encoding="utf-8",newline="") as handle:handle.write(text);handle.flush();os.fsync(handle.fileno())
  os.chmod(tmp,mode);os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def _state_path()->Path:return Path(os.getenv("TLDR_MAIL_STATE_PATH",str(DEFAULT_STATE)))
def _diagnostics_path()->Path:return Path(os.getenv("TLDR_MAIL_DIAGNOSTICS_PATH",str(DEFAULT_DIAGNOSTICS)))
def _load_state()->dict:
 p=_state_path()
 if not p.exists():return {"schema_version":STATE_VERSION,"pending":{}}
 try:x=json.loads(p.read_text())
 except Exception as exc:raise RuntimeError("mail_pending_state_invalid") from exc
 if x.get("schema_version")!=STATE_VERSION or not isinstance(x.get("pending"),dict):raise RuntimeError("mail_pending_state_invalid")
 return x
def _save_state(value:dict)->None:_atomic_write(_state_path(),json.dumps(value,sort_keys=True,indent=2)+"\n",0o600)
def _record_deletion_diagnostic(key:str,item:dict)->None:
 """Private-only recovery proof that a message was durably persisted and deleted; never exposed publicly."""
 p=_diagnostics_path()
 try:doc=json.loads(p.read_text())
 except Exception:doc={"schema_version":STATE_VERSION,"deletions":{}}
 if not isinstance(doc.get("deletions"),dict):doc["deletions"]={}
 doc["deletions"][key]={"mailbox":item.get("mailbox",MAILBOX),"uid":item["uid"],"message_id":item.get("message_id",""),"source_path":item["source_path"],"source_sha256":item["source_sha256"],"normalized_path":item.get("normalized_path"),"normalized_sha256":item.get("normalized_sha256"),"deleted_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())}
 _atomic_write(p,json.dumps(doc,sort_keys=True,indent=2)+"\n",0o600)
def persist_newsletter(imap,num:str,path:Path,text:str)->bool:
 """Privacy-normalize and durably persist without deleting the message."""
 if not is_approved_source(path.as_posix()) or path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent!=Path(".")):
  print(f"raw_privacy_violation path={path.as_posix()} category=path_outside_approved_sources host=unknown");return False
 try:prepared,categories=prepare_raw_source(text)
 except RawPrivacyError as exc:print(format_finding(exc.finding,path.as_posix()));return False
 if path.exists():
  if path.read_text()!=prepared:print(f"raw_source_conflict path={path.as_posix()}");return False
 else:_atomic_write(path,prepared)
 print(f"raw_newsletter_written path={path.as_posix()} categories={','.join(categories or ['none'])}");return True
def persist_normalized(root:Path,path:Path)->tuple[str,str]:
 """Parse a durably-written raw source into normalized issue JSON; returns (relpath, sha256)."""
 rel=path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
 source=resolve_source(root,rel);text=source.path.read_text(encoding="utf-8");issue=parse_source(source,text)
 output_root=validate_output_root(root,root/"generated");issue_path,_payload=write_issue(output_root,source,issue)
 digest="sha256:"+hashlib.sha256(issue_path.read_bytes()).hexdigest()
 return issue_path.relative_to(root).as_posix(),digest
def _plain_text(msg)->str:
 newsletter=""
 for part in msg.walk():
  if part.get_content_type()=="text/plain":
   payload=part.get_payload()
   if isinstance(payload,str):newsletter=quopri.decodestring(payload).decode("utf-8")
 return newsletter
def _connect():
 config=dotenv_values(".env");imap=imaplib.IMAP4_SSL("74.125.20.108");imap.login(config["email"],config["KEY"]);return imap
def ingest()->int:
 imap=_connect();imap.select(MAILBOX);failed=False;state=_load_state();root=Path(".").resolve()
 try:
  typ,data=imap.uid("search",None,'FROM "dan@tldrnewsletter.com"')
  if typ!="OK":return 1
  for raw_uid in reversed(data[0].decode().split()):
   typ,email_data=imap.uid("fetch",raw_uid,"(RFC822)")
   if typ!="OK" or not email_data or not isinstance(email_data[0],tuple):failed=True;continue
   msg=email.message_from_bytes(email_data[0][1]);sent=datetime.strptime(msg["Date"],"%a, %d %b %Y %H:%M:%S %z");sender=re.sub(r" <dan@tldrnewsletter.com>","",msg["From"]);sender=re.sub(r"=?utf-\w+\?Q\?.+\?=","",sender).replace(" =?","");filename=f"article_{sent.date().strftime('%d-%m-%Y')}.md";path=Path(sender)/filename;source=f"# Articles {sender} {sent.date().strftime('%d-%m-%Y')}\n\n{_plain_text(msg)}"
   if not persist_newsletter(imap,raw_uid,path,source):failed=True;continue
   try:normalized_path,normalized_sha256=persist_normalized(root,path)
   except Exception as exc:
    print(f"normalized_persist_failed path={path.as_posix()} error={exc}");failed=True;continue
   message_id=str(msg.get("Message-ID",""));key=hashlib.sha256((message_id+raw_uid).encode()).hexdigest()
   state["pending"][key]={"mailbox":MAILBOX,"uid":raw_uid,"message_id":message_id,"source_path":path.as_posix(),"publication_date":sent.date().isoformat(),"source_sha256":"sha256:"+hashlib.sha256(path.read_bytes()).hexdigest(),"normalized_path":normalized_path,"normalized_sha256":normalized_sha256}
   _save_state(state)
 finally:imap.close();imap.logout()
 return 1 if failed else 0
def _durably_checkpointed(item:dict)->bool:
 """Local recoverability gate: raw source and normalized issue data must both exist and match their recorded digests. Publication to origin/main is not required."""
 source_path=item.get("source_path");normalized_path=item.get("normalized_path");normalized_sha256=item.get("normalized_sha256")
 if not source_path or not normalized_path or not normalized_sha256:return False
 p=Path(source_path)
 if not p.is_file() or "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()!=item.get("source_sha256"):return False
 np=Path(normalized_path)
 if not np.is_file() or "sha256:"+hashlib.sha256(np.read_bytes()).hexdigest()!=normalized_sha256:return False
 return True
def _uid_present(imap,uid:str)->bool:
 status,data=imap.uid("SEARCH",None,f"UID {uid}");return status=="OK" and bool(data and data[0].strip())
def _expunge_uid(imap,uid:str)->None:
 try:
  typ,_=imap.uid("EXPUNGE",uid)
  if typ=="OK":return
 except imaplib.IMAP4.error:pass
 imap.expunge()
def acknowledge()->int:
 """Permanently delete durably-checkpointed messages from IMAP. Never deletes before the local checkpoint is verified."""
 state=_load_state();pending=state["pending"]
 if not pending:return 0
 eligible=[(key,item) for key,item in pending.items() if _durably_checkpointed(item)]
 if not eligible:return 0
 imap=_connect();imap.select(MAILBOX);failed=False
 try:
  for key,item in eligible:
   uid=item["uid"]
   if not _uid_present(imap,uid):
    del pending[key];_save_state(state);_record_deletion_diagnostic(key,item);print(f"mail_deleted_previously source_path={item['source_path']}");continue
   deleted=False
   try:
    a,_=imap.uid("STORE",uid,"+FLAGS","(\\Deleted)")
    if a=="OK":_expunge_uid(imap,uid);deleted=not _uid_present(imap,uid)
   except imaplib.IMAP4.error:deleted=not _uid_present(imap,uid)
   if deleted:del pending[key];_save_state(state);_record_deletion_diagnostic(key,item);print(f"mail_deleted source_path={item['source_path']}")
   else:failed=True
 finally:imap.close();imap.logout()
 return 1 if failed else 0
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--ack",action="store_true");a=p.parse_args();return acknowledge() if a.ack else ingest()
if __name__=="__main__":raise SystemExit(main())
