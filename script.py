"""Fetch TLDR newsletters durably; acknowledge mail only after published Git state."""
from __future__ import annotations
import argparse,email,hashlib,imaplib,json,os,quopri,re,subprocess,tempfile
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values
from tools.tldr_raw_privacy import RawPrivacyError,format_finding,is_approved_source,prepare_raw_source

STATE_VERSION="1.0.0";DEFAULT_STATE=Path.home()/".local/state/tldr_news/mail-pending.json";PROCESSED_LABEL="TLDR-Processed"
def _atomic_write(path:Path,text:str,mode:int=0o644)->None:
 path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix=".tldr-",dir=path.parent)
 try:
  with os.fdopen(fd,"w",encoding="utf-8",newline="") as handle:handle.write(text);handle.flush();os.fsync(handle.fileno())
  os.chmod(tmp,mode);os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def _state_path()->Path:return Path(os.getenv("TLDR_MAIL_STATE_PATH",str(DEFAULT_STATE)))
def _load_state()->dict:
 p=_state_path()
 if not p.exists():return {"schema_version":STATE_VERSION,"pending":{}}
 try:x=json.loads(p.read_text())
 except Exception as exc:raise RuntimeError("mail_pending_state_invalid") from exc
 if x.get("schema_version")!=STATE_VERSION or not isinstance(x.get("pending"),dict):raise RuntimeError("mail_pending_state_invalid")
 return x
def _save_state(value:dict)->None:_atomic_write(_state_path(),json.dumps(value,sort_keys=True,indent=2)+"\n",0o600)
def persist_newsletter(imap,num:str,path:Path,text:str)->bool:
 """Privacy-normalize and durably persist without acknowledging the message."""
 if not is_approved_source(path.as_posix()) or path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent!=Path(".")):
  print(f"raw_privacy_violation path={path.as_posix()} category=path_outside_approved_sources host=unknown");return False
 try:prepared,categories=prepare_raw_source(text)
 except RawPrivacyError as exc:print(format_finding(exc.finding,path.as_posix()));return False
 if path.exists():
  if path.read_text()!=prepared:print(f"raw_source_conflict path={path.as_posix()}");return False
 else:_atomic_write(path,prepared)
 print(f"raw_newsletter_written path={path.as_posix()} categories={','.join(categories or ['none'])}");return True
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
 imap=_connect();imap.select("inbox");failed=False;state=_load_state()
 try:
  typ,data=imap.uid("search",None,'FROM "dan@tldrnewsletter.com"')
  if typ!="OK":return 1
  for raw_uid in reversed(data[0].decode().split()):
   typ,email_data=imap.uid("fetch",raw_uid,"(RFC822)")
   if typ!="OK" or not email_data or not isinstance(email_data[0],tuple):failed=True;continue
   msg=email.message_from_bytes(email_data[0][1]);sent=datetime.strptime(msg["Date"],"%a, %d %b %Y %H:%M:%S %z");sender=re.sub(r" <dan@tldrnewsletter.com>","",msg["From"]);sender=re.sub(r"=?utf-\w+\?Q\?.+\?=","",sender).replace(" =?","");filename=f"article_{sent.date().strftime('%d-%m-%Y')}.md";path=Path(sender)/filename;source=f"# Articles {sender} {sent.date().strftime('%d-%m-%Y')}\n\n{_plain_text(msg)}"
   if not persist_newsletter(imap,raw_uid,path,source):failed=True;continue
   key=hashlib.sha256((str(msg.get("Message-ID",""))+raw_uid).encode()).hexdigest();state["pending"][key]={"uid":raw_uid,"source_path":path.as_posix(),"publication_date":sent.date().isoformat(),"source_sha256":"sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()};_save_state(state)
 finally:imap.close();imap.logout()
 return 1 if failed else 0
def _tracked_at_origin(path:str)->bool:return subprocess.run(["git","cat-file","-e",f"origin/main:{path}"],capture_output=True).returncode==0
def acknowledge()->int:
 state=_load_state();pending=state["pending"]
 if not pending:return 0
 eligible=[]
 for key,item in pending.items():
  p=Path(item["source_path"]);editorial=f"generated/editorial/{item['publication_date'][:4]}/{item['publication_date']}.json"
  if p.is_file() and "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()==item["source_sha256"] and _tracked_at_origin(item["source_path"]) and _tracked_at_origin(editorial):eligible.append((key,item))
 if not eligible:return 0
 imap=_connect();imap.select("inbox");imap.create(PROCESSED_LABEL);failed=False
 try:
  for key,item in eligible:
   a,_=imap.uid("STORE",item["uid"],"+X-GM-LABELS",f'("{PROCESSED_LABEL}")');b,_=imap.uid("STORE",item["uid"],"-X-GM-LABELS",'(\\Inbox)')
   acknowledged=a=="OK" and b=="OK"
   if not acknowledged:
    status,data=imap.uid("SEARCH",None,f"UID {item['uid']}");acknowledged=status=="OK" and not (data and data[0].strip())
   if acknowledged:del pending[key];_save_state(state);print(f"mail_acknowledged source_path={item['source_path']}")
   else:failed=True
 finally:imap.close();imap.logout()
 return 1 if failed else 0
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--ack",action="store_true");a=p.parse_args();return acknowledge() if a.ack else ingest()
if __name__=="__main__":raise SystemExit(main())
