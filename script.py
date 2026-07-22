"""Fetch new TLDR newsletters and write privacy-safe raw source files."""
from __future__ import annotations

import email
import imaplib
import os
import quopri
import re
import tempfile
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values
from tools.tldr_raw_privacy import RawPrivacyError,format_finding,is_approved_source,prepare_raw_source


def _atomic_write(path:Path,text:str)->None:
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix=".tldr-raw-",dir=path.parent)
 try:
  with os.fdopen(fd,"w",encoding="utf-8",newline="") as handle:
   handle.write(text);handle.flush();os.fsync(handle.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)


def persist_newsletter(imap,num:str,path:Path,text:str)->bool:
 """Prepare/write one newsletter, deleting mail only after a safe write."""
 if not is_approved_source(path.as_posix()) or path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent!=Path(".")):
  print(f"raw_privacy_violation path={path.as_posix()} category=path_outside_approved_sources host=unknown")
  return False
 try:prepared,categories=prepare_raw_source(text)
 except RawPrivacyError as exc:
  print(format_finding(exc.finding,path.as_posix()))
  return False
 _atomic_write(path,prepared)
 print(f"raw_newsletter_written path={path.as_posix()} categories={','.join(categories or ['none'])}")
 imap.store(num,"+FLAGS","\\Deleted");imap.expunge()
 return True


def _plain_text(msg)->str:
 newsletter=""
 for part in msg.walk():
  if part.get_content_type()=="text/plain":
   payload=part.get_payload()
   if isinstance(payload,str):newsletter=quopri.decodestring(payload).decode("utf-8")
 return newsletter


def main()->int:
 config=dotenv_values(".env");imap=imaplib.IMAP4_SSL("74.125.20.108")
 imap.login(config["email"],config["KEY"]);imap.select("inbox")
 failed=False
 try:
  typ,data=imap.search(None,'FROM "dan@tldrnewsletter.com"')
  if typ!="OK":return 1
  ids=[int(value) for value in data[0].decode().split()]
  for number in reversed(ids):
   num=str(number);_,email_data=imap.fetch(num,"(RFC822)");msg=email.message_from_bytes(email_data[0][1])
   sent=datetime.strptime(msg["Date"],"%a, %d %b %Y %H:%M:%S %z")
   sender=re.sub(r" <dan@tldrnewsletter.com>","",msg["From"])
   sender=re.sub(r"=?utf-\w+\?Q\?.+\?=","",sender).replace(" =?","")
   filename=f"article_{sent.date().strftime('%d-%m-%Y')}.md";path=Path(sender)/filename
   source=f"# Articles {sender} {sent.date().strftime('%d-%m-%Y')}\n\n{_plain_text(msg)}"
   if not persist_newsletter(imap,num,path,source):failed=True
 finally:
  imap.close();imap.logout()
 return 1 if failed else 0


if __name__=="__main__":raise SystemExit(main())
