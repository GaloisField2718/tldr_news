"""Privacy preparation and staged-index gate for raw TLDR newsletters."""
from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit, urlunsplit

_URL_RE=re.compile(r"https?://[^\s<>\"']+",re.IGNORECASE)
_ALWAYS_SENSITIVE={"access_token","refresh_token","id_token","api_key","apikey","client_secret","auth_token","authorization","password","passwd","session","session_id","sessionid","jwt","signature","x_amz_signature","x_amz_credential","x_amz_security_token","x_goog_signature","x_goog_credential"}
_SUBSCRIBER_KEYS={"email","email_address","subscriber","subscriber_id","contact_id"}
_OBSERVED_CANONICAL={("stratechery.com","access_token"),("www.stratechery.com","access_token")}
_PRIVATE_HOSTS={"refer.tldr.tech","hub.sparklp.co"}
_MANAGEMENT_PATH=re.compile(r"(^|/)(unsubscribe|manage|preferences?|subscriptions?|account|settings|email-preferences)(/|$)",re.I)

@dataclass(frozen=True)
class Finding:
 category:str
 host:str
 key:str|None=None

class RawPrivacyError(Exception):
 def __init__(self,finding:Finding):self.finding=finding;super().__init__(format_finding(finding))

def _key(raw:str)->str:return unquote_plus(raw.split("=",1)[0]).strip().lower().replace("-","_")
def _query_pairs(query:str)->list[tuple[str,str]]:
 return [(_key(q),q) for q in html.unescape(query).split("&") if q]
def _host(parts)->str:return (parts.hostname or "").lower()
def _private_url(parts,pairs:list[tuple[str,str]])->bool:
 host=_host(parts);path=parts.path or ""
 if host in _PRIVATE_HOSTS:return True
 if host.endswith(".tldrnewsletter.com") and (path.startswith("/web-version") or _MANAGEMENT_PATH.search(path)):return True
 if (host=="tldr.tech" or host.endswith(".tldr.tech")) and _MANAGEMENT_PATH.search(path):return True
 return any(k in _SUBSCRIBER_KEYS for k,_ in pairs)

def inspect_raw_privacy(text:str)->list[Finding]:
 findings=[]
 for match in _URL_RE.finditer(text):
  raw=match.group(0).rstrip(").,;]")
  try:parts=urlsplit(raw)
  except ValueError:
   findings.append(Finding("invalid_url",""));continue
  host=_host(parts);pairs=_query_pairs(parts.query)
  if parts.username is not None or parts.password is not None:findings.append(Finding("url_userinfo",host))
  if _private_url(parts,pairs):findings.append(Finding("subscriber_or_management_url",host,next((k for k,_ in pairs if k in _SUBSCRIBER_KEYS),None)))
  for key,_ in pairs:
   if key in _ALWAYS_SENSITIVE:findings.append(Finding("credential_query_parameter",host,key))
 return list(dict.fromkeys(findings))

def _sanitize_url(raw:str)->tuple[str,list[str]]:
 suffix=raw[len(raw.rstrip(").,;]")):];url=raw[:len(raw)-len(suffix)] if suffix else raw
 parts=urlsplit(url);host=_host(parts);pairs=_query_pairs(parts.query)
 if parts.username is not None or parts.password is not None:raise RawPrivacyError(Finding("url_userinfo",host))
 if _private_url(parts,pairs):return suffix,["subscriber_or_management_url"]
 sensitive={k for k,_ in pairs if k in _ALWAYS_SENSITIVE}
 if sensitive:
  unresolved=sorted(k for k in sensitive if (host,k) not in _OBSERVED_CANONICAL)
  if unresolved:raise RawPrivacyError(Finding("credential_query_parameter",host,unresolved[0]))
  kept=[raw_pair for k,raw_pair in pairs if k not in sensitive]
  url=urlunsplit((parts.scheme,parts.netloc,parts.path,"&".join(kept),parts.fragment))
  return url+suffix,["credential_parameter_removed"]
 return url+suffix,[]

def prepare_raw_source(text:str)->tuple[str,list[str]]:
 """Normalize and sanitize one complete raw newsletter deterministically."""
 text=text.replace("\r\n","\n").replace("\r","\n");categories=[]
 def replace(match):
  replacement,found=_sanitize_url(match.group(0));categories.extend(found);return replacement
 text=_URL_RE.sub(replace,text)
 lines=[re.sub(r"[ \t]+$","",line) for line in text.split("\n")]
 while lines and lines[-1]=="":lines.pop()
 return "\n".join(lines)+"\n",sorted(set(categories))

def is_approved_source(path:str)->bool:
 p=Path(path)
 return not p.is_absolute() and len(p.parts)>=2 and (p.parts[0]=="TLDR" or p.parts[0].startswith("TLDR ")) and p.suffix.lower()==".md" and ".." not in p.parts

def staged_source_paths()->list[str]:
 raw=subprocess.run(["git","diff","--cached","--name-only","-z","--diff-filter=ACMR"],check=True,capture_output=True).stdout
 return [os.fsdecode(p) for p in raw.split(b"\0") if p and is_approved_source(os.fsdecode(p))]

def indexed_blob(path:str)->bytes:
 entry=subprocess.run(["git","ls-files","-s","-z","--",path],check=True,capture_output=True).stdout.split(b"\0",1)[0]
 if not entry:raise RuntimeError("staged_blob_missing")
 fields=entry.split(b" ",2)
 if len(fields)<3:raise RuntimeError("staged_blob_invalid")
 return subprocess.run(["git","cat-file","blob",fields[1].decode("ascii")],check=True,capture_output=True).stdout

def format_finding(finding:Finding,path:str|None=None)->str:
 fields=["raw_privacy_violation"]
 if path:fields.append(f"path={path}")
 fields.extend((f"category={finding.category}",f"host={finding.host or 'unknown'}"))
 if finding.key:fields.append(f"key={finding.key}")
 return " ".join(fields)

def check_staged()->int:
 failed=False
 for path in staged_source_paths():
  try:text=indexed_blob(path).decode("utf-8")
  except (UnicodeDecodeError,RuntimeError,subprocess.SubprocessError):
   print(f"raw_privacy_violation path={path} category=unreadable_staged_blob host=unknown",file=sys.stderr);failed=True;continue
  for finding in inspect_raw_privacy(text):print(format_finding(finding,path),file=sys.stderr);failed=True
 return 1 if failed else 0

def _repo_root()->Path:
 raw=subprocess.run(["git","rev-parse","--show-toplevel"],check=True,capture_output=True).stdout
 return Path(os.fsdecode(raw.rstrip(b"\n"))).resolve()

def sanitize_paths(paths:list[str],check:bool=False)->int:
 root=_repo_root();changed=False;failed=False
 for supplied in paths:
  candidate=Path(supplied) if Path(supplied).is_absolute() else root/supplied
  if candidate.is_symlink():
   print(f"raw_privacy_violation path={supplied} category=path_outside_approved_sources host=unknown",file=sys.stderr);failed=True;continue
  try:candidate=candidate.resolve(strict=True);relative=candidate.relative_to(root)
  except (OSError,ValueError):
   print(f"raw_privacy_violation path={supplied} category=path_outside_approved_sources host=unknown",file=sys.stderr);failed=True;continue
  rel=relative.as_posix()
  if not is_approved_source(rel) or not candidate.is_file():
   print(f"raw_privacy_violation path={rel} category=path_outside_approved_sources host=unknown",file=sys.stderr);failed=True;continue
  try:prepared,categories=prepare_raw_source(candidate.read_text(encoding="utf-8"))
  except RawPrivacyError as exc:
   print(format_finding(exc.finding,rel),file=sys.stderr);failed=True;continue
  original=candidate.read_text(encoding="utf-8")
  if prepared!=original:
   changed=True;print(f"raw_privacy_changed path={rel} categories={','.join(categories or ['format_normalized'])}")
   if not check:
    mode=candidate.stat().st_mode & 0o777
    fd,tmp=tempfile.mkstemp(prefix=".tldr-raw-",dir=candidate.parent)
    try:
     with os.fdopen(fd,"w",encoding="utf-8",newline="") as handle:handle.write(prepared);handle.flush();os.fsync(handle.fileno())
     os.chmod(tmp,mode);os.replace(tmp,candidate)
    finally:
     if os.path.exists(tmp):os.unlink(tmp)
 return 1 if failed or (check and changed) else 0

def main(argv:list[str]|None=None)->int:
 parser=argparse.ArgumentParser(prog="python -m tools.tldr_raw_privacy");sub=parser.add_subparsers(dest="command",required=True)
 sub.add_parser("check-staged")
 sanitize=sub.add_parser("sanitize");sanitize.add_argument("--check",action="store_true");sanitize.add_argument("paths",nargs="+")
 args=parser.parse_args(argv)
 return check_staged() if args.command=="check-staged" else sanitize_paths(args.paths,args.check)

if __name__=="__main__":raise SystemExit(main())
