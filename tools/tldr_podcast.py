#!/usr/bin/env python3
"""Two-step Daily Index podcast runtime; generate is private, publish is explicit."""
from __future__ import annotations
import argparse,fcntl,hashlib,json,os,re,shutil,subprocess,tempfile,time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any,Callable
import requests
from tools.tldr_editorial.config import Config
from tools.tldr_editorial.r2_storage import R2Storage
from tools.tldr_tts_calibration import CAPABILITIES,Candidate,CalibrationError,SpeechHTTPError,_private_json,assemble,build_request,http_diagnostic,request_turn,turn_descriptor,validate_turn

EDITORIAL_MODEL="openai/gpt-5.6-luna"; CHAT_URL="https://openrouter.ai/api/v1/chat/completions"; PROFILE="daily-index-duo-v1"; STATE_VERSION="1.0.0"
MIN_DURATION=270;PREFERRED_DURATION=330;MAX_DURATION=390;DEFAULT_COST_CEILING=1.0
DEFAULT=Candidate("xai","x-ai/grok-voice-tts-1.0",{"host":"eve","analyst":"rex"},{"prompt":"0.000015","completion":"0"},"characters","calibration-20260722",("mp3",),("speech",),("response_format",),15000)
FALLBACK=Candidate("mistral","mistralai/voxtral-mini-tts-2603",{"host":"en_paul_neutral","analyst":"gb_jane_neutral"},{"prompt":"0.000016","completion":"0"},"characters","calibration-20260722",("mp3",),("speech",),("response_format",),4096)
URL_RE=re.compile(r"(?:https?://|www\.)\S+",re.I);MARKDOWN_RE=re.compile(r"(?:^|\s)[#>*_`]|\[[^]]+\]\([^)]*\)");STAGE_RE=re.compile(r"\[[^]]+\]|\([^)]*(?:laugh|pause|music|sound)[^)]*\)",re.I)
class PodcastError(RuntimeError):pass
@dataclass(frozen=True)
class PodcastProfile: candidate:Candidate;fallback:Candidate|None;cost_ceiling:float=DEFAULT_COST_CEILING

def sha256(path:Path)->str:return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()
def git_head(root:Path)->str:return subprocess.run(["git","rev-parse","HEAD"],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
def podcast_key(d:str,digest:str)->str:
 if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",d) or not re.fullmatch(r"sha256:[0-9a-f]{64}",digest):raise PodcastError("podcast_key_invalid")
 return f"podcast/daily/{d[:4]}/{d[5:7]}/{d[8:]}/{digest[7:]}.mp3"
def source_path(root:Path,d:str)->Path:return root/"generated"/"editorial"/d[:4]/f"{d}.json"
def artifact_path(root:Path,d:str)->Path:return root/"generated"/"podcast"/d[:4]/f"{d}.json"
def runtime_dir(d:str)->Path:return Path(os.getenv("TLDR_PODCAST_RUNTIME_ROOT","/home/galois/tldr-podcast-runtime"))/d
def expected_open_close(d:str)->tuple[str,str]:return ("speaker_a","speaker_b") if date.fromisoformat(d).day%2 else ("speaker_b","speaker_a")
def estimate_seconds(turns:list[dict[str,Any]])->int:return round(sum(len(t["text"]) for t in turns)/15.5+sum(t.get("pause_after_ms",0) for t in turns)/1000)
def profile_from_args(use_fallback:bool,cost_ceiling:float)->PodcastProfile:
 if use_fallback:raise PodcastError("fallback_requires_separate_authorization")
 if not 0<cost_ceiling<=DEFAULT_COST_CEILING:raise PodcastError("podcast_cost_ceiling_invalid")
 return PodcastProfile(DEFAULT,FALLBACK,cost_ceiling)
def estimate_cost(candidate:Candidate,characters:int)->float:return round(float(candidate.pricing["prompt"])*characters,6)
def load_source(root:Path,d:str)->tuple[dict[str,Any],str]:
 p=source_path(root,d)
 if not p.is_file():raise PodcastError("source_daily_artifact_missing")
 x=json.loads(p.read_text())
 if x.get("date")!=d or x.get("status")!="ai_complete":raise PodcastError("source_daily_artifact_invalid")
 return x,sha256(p)
def source_facts(source:dict[str,Any])->str:
 brief=source.get("plan",{}).get("visual_brief",{});return "\n".join(str(brief.get(k,"")) for k in ("central_subject","editorial_idea","visual_relationship","composition"))[:12000]
def validate_script(script:dict[str,Any],source_digest:str)->dict[str,Any]:
 required={"schema_version","publication_date","episode_title","summary","source_artifact_sha256","estimated_duration_seconds","speakers","turns"}
 if set(script)!=required or script["schema_version"]!="1.0.0" or script["source_artifact_sha256"]!=source_digest:raise PodcastError("podcast_script_schema_invalid")
 turns=script["turns"]
 if not isinstance(turns,list) or not 24<=len(turns)<=36 or set(script["speakers"])!={"speaker_a","speaker_b"}:raise PodcastError("podcast_script_schema_invalid")
 opener,closer=expected_open_close(script["publication_date"])
 if turns[0].get("speaker")!=opener or turns[-1].get("speaker")!=closer:raise PodcastError("podcast_rotation_invalid")
 chars={"speaker_a":0,"speaker_b":0};asks=set();explains=set();nuances=set();previous=None;run=0
 for i,t in enumerate(turns,1):
  if set(t)!={"turn_id","speaker","text","pause_after_ms"} or t.get("turn_id")!=f"t{i:03}" or t.get("speaker") not in chars or not isinstance(t.get("text"),str) or not t["text"].strip() or not isinstance(t.get("pause_after_ms"),int) or not 0<=t["pause_after_ms"]<=2000:raise PodcastError("podcast_turn_invalid")
  text=t["text"]
  if URL_RE.search(text) or MARKDOWN_RE.search(text) or STAGE_RE.search(text):raise PodcastError("podcast_spoken_markup_invalid")
  chars[t["speaker"]]+=len(text);run=run+1 if previous==t["speaker"] else 1;previous=t["speaker"]
  if run>3:raise PodcastError("podcast_consecutive_turns_invalid")
  low=text.lower()
  if "?" in text:asks.add(t["speaker"])
  if any(w in low for w in ("because","means","works","uses","happens when")):explains.add(t["speaker"])
  if any(w in low for w in ("but ","however","although","may ","could ","not necessarily")):nuances.add(t["speaker"])
 total=sum(chars.values());shares={k:v/total for k,v in chars.items()}
 duration=estimate_seconds(turns)
 if not all(.4<=v<=.6 for v in shares.values()) or asks!=set(chars) or explains!=set(chars) or nuances!=set(chars):raise PodcastError("podcast_balance_invalid")
 if not MIN_DURATION<=duration<=MAX_DURATION or abs(duration-int(script["estimated_duration_seconds"]))>15:raise PodcastError("podcast_duration_invalid")
 return {"duration_seconds":duration,"characters":chars,"shares":shares,"turn_count":len(turns)}
def validate_grounding(script:dict[str,Any],source:dict[str,Any])->None:
 facts=source_facts(source).lower(); words={w for w in re.findall(r"[a-z]{5,}",facts)}; spoken=" ".join(t["text"].lower() for t in script["turns"]); overlap=sum(w in spoken for w in words)
 if overlap<3:raise PodcastError("podcast_source_grounding_invalid")
def editorial_prompt(source:dict[str,Any],digest:str,d:str)->str:
 opener,closer=expected_open_close(d)
 return f"""Write only strict JSON matching the supplied podcast schema. Ground every factual claim only in SOURCE FACTS. Make a calm 24-36 turn Daily Index technology dialogue of 5000-6000 characters, 270-390 seconds. speaker_a and speaker_b are equal cohosts: each asks a substantive question, explains a mechanism, and adds nuance; both have 40-60% characters; at most three consecutive turns. {opener} opens and {closer} closes. No URLs, markdown, stage directions, invented facts, or promotional language. SOURCE SHA: {digest}. SOURCE FACTS:\n{source_facts(source)}\nSchema fields: schema_version 1.0.0, publication_date, episode_title, summary, source_artifact_sha256, estimated_duration_seconds, speakers={{speaker_a:{{role:cohost}},speaker_b:{{role:cohost}}}}, turns=[{{turn_id:t001,speaker:speaker_a,text,pause_after_ms}}]."""
def extract_script(response:Any)->dict[str,Any]:
 try: content=response["choices"][0]["message"]["content"];return json.loads(content)
 except (KeyError,IndexError,TypeError,json.JSONDecodeError) as exc:raise PodcastError("podcast_editorial_response_invalid") from exc
def _atomic_json(path:Path,value:dict[str,Any],private:bool=False)->None:
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700 if private else 0o755);tmp=path.with_name("."+path.name+".tmp");tmp.write_text(json.dumps(value,sort_keys=True,indent=2)+"\n");os.chmod(tmp,0o600 if private else 0o644);os.replace(tmp,path)
def initial_state(root:Path,d:str,source_digest:str,profile:PodcastProfile)->dict[str,Any]:return {"schema_version":STATE_VERSION,"publication_date":d,"source_artifact_sha256":source_digest,"production_code_head":git_head(root),"profile":{"model":profile.candidate.model,"voices":profile.candidate.voices},"script_status":"pending","script_sha256":None,"planned_turns":[],"completed_turns":{},"failed_turn":None,"request_attempts":0,"retries":0,"estimated_cost_usd":0.0,"measured_cost_usd":None,"audio_validation":None,"assembly_status":"pending","upload_status":"pending","artifact_status":"pending","frontend_status":"pending","accepted":False}
def load_state(root:Path,d:str,source_digest:str,profile:PodcastProfile)->tuple[Path,dict[str,Any]]:
 rd=runtime_dir(d);rd.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(rd,0o700);p=rd/"state.json"
 if not p.exists():state=initial_state(root,d,source_digest,profile);_atomic_json(p,state,True);return rd,state
 try:state=json.loads(p.read_text())
 except Exception as exc:raise PodcastError("podcast_runtime_state_malformed") from exc
 expected=initial_state(root,d,source_digest,profile)
 for k in ("schema_version","publication_date","source_artifact_sha256","production_code_head","profile"):
  if state.get(k)!=expected[k]:raise PodcastError("podcast_runtime_state_conflict")
 return rd,state
def save_state(rd:Path,state:dict[str,Any])->None:_atomic_json(rd/"state.json",state,True)
@contextmanager
def date_lock(rd:Path):
 lock=rd/"runtime.lock";fd=os.open(lock,os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise PodcastError("podcast_runtime_locked")
  yield
 finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
def projected_cost(state:dict[str,Any],next_cost:float,ceiling:float)->None:
 known=state["measured_cost_usd"] if state["measured_cost_usd"] is not None else state["estimated_cost_usd"]
 if float(known)+next_cost>ceiling:raise PodcastError("podcast_cost_ceiling_exceeded")
def editorial_request(post:Callable[...,Any],key:str,prompt:str)->dict[str,Any]:
 body={"model":EDITORIAL_MODEL,"messages":[{"role":"user","content":prompt}],"response_format":{"type":"json_object"}}
 r=post(CHAT_URL,headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},json=body,timeout=120)
 if not 200<=r.status_code<300:raise PodcastError(f"podcast_editorial_http_{r.status_code}")
 return extract_script(r.json())
def generate_script(post:Callable[...,Any],key:str,source:dict[str,Any],digest:str,d:str,state:dict[str,Any],ceiling:float)->dict[str,Any]:
 projected_cost(state,.10,ceiling);prompt=editorial_prompt(source,digest,d)
 for attempt in range(2):
  state["request_attempts"]+=1;state["estimated_cost_usd"]+=.10
  try:s=editorial_request(post,key,prompt);validate_script(s,digest);validate_grounding(s,source);return s
  except PodcastError as exc:
   if attempt or "response_invalid" in str(exc):raise
   state["retries"]+=1;prompt+="\nRepair the previous JSON to satisfy every schema and balance rule; return JSON only."
 raise PodcastError("podcast_script_generation_failed")
def tts_turn(post:Callable[...,Any],key:str,candidate:Candidate,turn:dict[str,Any],rd:Path,state:dict[str,Any],ceiling:float)->dict[str,Any]:
 tid=turn["turn_id"];existing=state["completed_turns"].get(tid)
 if existing:return existing
 private=rd/"turns";private.mkdir(exist_ok=True,mode=0o700);body=build_request(candidate,{"speaker":"host" if turn["speaker"]=="speaker_a" else "analyst","text":turn["text"]});one=estimate_cost(candidate,len(turn["text"]))
 for retry in range(2):
  projected_cost(state,one,ceiling);state["request_attempts"]+=1
  try:audio,meta=request_turn(post,key,body,max_retries=0,turn_id=tid,diagnostic_dir=rd/"diagnostics")
  except SpeechHTTPError as exc:
   if retry or not (exc.status==429 or 500<=exc.status<600):state["failed_turn"]=tid;raise PodcastError("podcast_tts_unrecoverable") from exc
   state["retries"]+=1;state["estimated_cost_usd"]+=one;continue
  desc=turn_descriptor(candidate,"production",tid,private,str(meta["content_type"]));tmp=desc.path.with_suffix(desc.path.suffix+".tmp");tmp.write_bytes(audio);os.chmod(tmp,0o600);os.replace(tmp,desc.path);valid=validate_turn(desc);record={"path":desc.path.name,"sha256":sha256(desc.path),"bytes":valid["bytes"],"duration_seconds":valid["duration_seconds"],"speaker":turn["speaker"],"attempts":retry+1};state["completed_turns"][tid]=record;state["estimated_cost_usd"]+=one;return record
 raise PodcastError("podcast_tts_failed")
def measure_audio(path:Path)->dict[str,Any]:
 r=subprocess.run(["ffprobe","-v","error","-show_entries","stream=codec_name,sample_rate,channels:format=duration","-of","json",str(path)],capture_output=True,text=True,check=True);x=json.loads(r.stdout);s=x["streams"][0]
 if s["codec_name"]!="mp3" or int(s["sample_rate"])!=24000 or int(s["channels"])!=1:raise PodcastError("podcast_final_format_invalid")
 loud=subprocess.run(["ffmpeg","-v","error","-i",str(path),"-filter:a","ebur128=peak=true","-f","null","-"],capture_output=True,text=True).stderr
 return {"duration_seconds":round(float(x["format"]["duration"]),3),"bytes":path.stat().st_size,"sha256":sha256(path),"codec":"mp3","sample_rate":24000,"channels":1,"loudness_report":loud[-4096:]}
def assemble_episode(rd:Path,script:dict[str,Any],state:dict[str,Any])->Path:
 if len(state["completed_turns"])!=len(script["turns"]):raise PodcastError("podcast_turns_incomplete")
 turns=[]
 for t in script["turns"]:
  rec=state["completed_turns"].get(t["turn_id"])
  if not rec:raise PodcastError("podcast_turns_incomplete")
  p=rd/"turns"/rec["path"];turns.append(turn_descriptor(DEFAULT,"production",t["turn_id"],p.parent,"audio/mpeg"))
 final=rd/"episode.mp3";assemble(turns,[t["pause_after_ms"] for t in script["turns"]],final);m=measure_audio(final)
 if not MIN_DURATION<=m["duration_seconds"]<=MAX_DURATION:final.unlink(missing_ok=True);raise PodcastError("podcast_final_duration_invalid")
 state["audio_validation"]=m;state["assembly_status"]="complete";return final
def upload_audio(storage:Any,path:Path,d:str,metrics:dict[str,Any])->tuple[str,bool]:
 key=podcast_key(d,metrics["sha256"]);head=storage.head_object(key)
 if head:
  if head.get("ContentLength")!=metrics["bytes"]:raise PodcastError("podcast_r2_conflict")
  return storage.build_public_url(key),False
 try:storage.client.upload_file(str(path),storage.config.r2_bucket,key,ExtraArgs={"ContentType":"audio/mpeg","CacheControl":"public, max-age=31536000, immutable","Metadata":{"sha256":metrics["sha256"][7:],"date":d,"generator-version":"1.0.0"}})
 except Exception as exc:raise PodcastError("podcast_r2_upload_failed") from exc
 head=storage.head_object(key)
 if not head or head.get("ContentLength")!=metrics["bytes"] or str(head.get("ContentType","")).split(";",1)[0]!="audio/mpeg":raise PodcastError("podcast_r2_verify_failed")
 return storage.build_public_url(key),True
def public_artifact(d:str,script:dict[str,Any],source_digest:str,metrics:dict[str,Any],url:str)->dict[str,Any]:return {"schema_version":"1.0.0","publication_date":d,"episode_title":script["episode_title"],"summary":script["summary"],"duration_seconds":metrics["duration_seconds"],"audio_url":url,"audio_sha256":metrics["sha256"],"audio_bytes":metrics["bytes"],"mime_type":"audio/mpeg","source_artifact_sha256":source_digest,"script_sha256":sha256(runtime_dir(d)/"script.json"),"status":"published","generated_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"speaker_profile":PROFILE}
def preflight(root:Path,d:str,cost:float)->dict[str,Any]:
 source,digest=load_source(root,d);p=profile_from_args(False,cost);rd=runtime_dir(d);target=5115;tts=estimate_cost(DEFAULT,target)
 if .20+tts>cost:raise PodcastError("podcast_estimated_cost_exceeds_ceiling")
 return {"ready":True,"paid_calls":0,"publication_date":d,"source_artifact_sha256":digest,"selected_model":DEFAULT.model,"voices":DEFAULT.voices,"planned_editorial_requests":1,"maximum_repairs":1,"planned_tts_turns":"24-36","maximum_tts_attempts":72,"target_duration_seconds":PREFERRED_DURATION,"conservative_editorial_cost_usd":.20,"conservative_tts_cost_usd":tts,"total_ceiling_usd":cost,"private_runtime_directory":str(rd),"private_mp3_path":str(rd/"episode.mp3"),"r2_target_pattern":f"podcast/daily/{d[:4]}/{d[5:7]}/{d[8:]}/<sha256>.mp3","podcast_artifact_path":str(artifact_path(root,d)),"frontend_plan":"prepare only after verified R2 publication; no frontend call in generate","cron_active":False}
def generate(root:Path,d:str,key:str,post:Callable[...,Any]=requests.post,cost:float=1.0)->dict[str,Any]:
 source,digest=load_source(root,d);profile=profile_from_args(False,cost);rd,state=load_state(root,d,digest,profile)
 with date_lock(rd):
  script_file=rd/"script.json"
  if script_file.exists():script=json.loads(script_file.read_text());validate_script(script,digest);validate_grounding(script,source)
  else:
   script=generate_script(post,key,source,digest,d,state,cost);_atomic_json(script_file,script,True);state["script_status"]="complete";state["script_sha256"]=sha256(script_file);state["planned_turns"]=[t["turn_id"] for t in script["turns"]];save_state(rd,state)
  for turn in script["turns"]:tts_turn(post,key,profile.candidate,turn,rd,state,cost);save_state(rd,state)
  final=rd/"episode.mp3" if state["assembly_status"]=="complete" else assemble_episode(rd,script,state);save_state(rd,state);return {"private_audio":str(final),"state":state}
def publish(root:Path,d:str,storage:Any,accept:bool)->dict[str,Any]:
 source,digest=load_source(root,d);profile=profile_from_args(False,1.0);rd,state=load_state(root,d,digest,profile)
 with date_lock(rd):
  if not accept:raise PodcastError("podcast_human_acceptance_required")
  state["accepted"]=True;save_state(rd,state)
  final=rd/"episode.mp3";metrics=state.get("audio_validation")
  if not final.is_file() or not metrics or measure_audio(final)["sha256"]!=metrics["sha256"]:raise PodcastError("podcast_private_audio_invalid")
  url,_=upload_audio(storage,final,d,metrics);state["upload_status"]="verified";script=json.loads((rd/"script.json").read_text());doc=public_artifact(d,script,digest,metrics,url);out=artifact_path(root,d)
  if out.exists() and json.loads(out.read_text())!=doc:raise PodcastError("podcast_artifact_conflict")
  _atomic_json(out,doc);state["artifact_status"]="published";save_state(rd,state);return doc
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("command",choices=("preflight","generate","publish"));p.add_argument("--date",required=True);p.add_argument("--authorize-paid",action="store_true");p.add_argument("--authorize-publish",action="store_true");p.add_argument("--accept",action="store_true");p.add_argument("--cost-ceiling",type=float,default=1.0);a=p.parse_args();root=Path.cwd()
 if a.command=="preflight":print(json.dumps(preflight(root,a.date,a.cost_ceiling),sort_keys=True,indent=2));return 0
 if a.command=="generate":
  if not a.authorize_paid:raise PodcastError("explicit_paid_authorization_required")
  key=os.getenv("OPENROUTER_API_KEY");
  if not key:raise PodcastError("openrouter_key_missing")
  print(json.dumps(generate(root,a.date,key,cost=a.cost_ceiling),sort_keys=True));return 0
 if not a.authorize_publish:raise PodcastError("explicit_publish_authorization_required")
 cfg=Config.from_env();cfg.require_r2();print(json.dumps(publish(root,a.date,R2Storage(cfg),a.accept),sort_keys=True));return 0
if __name__=="__main__":main()
