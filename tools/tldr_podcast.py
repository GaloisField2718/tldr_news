#!/usr/bin/env python3
"""Daily Index podcast production contract. Paid generation requires explicit authorization."""
from __future__ import annotations
import argparse, hashlib, json, re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from tools.tldr_tts_calibration import CAPABILITIES, Candidate, build_request, request_turn, turn_descriptor, validate_turn, assemble

EDITORIAL_MODEL="openai/gpt-5.6-luna"
PROFILE="daily-index-duo-v1"
DEFAULT=Candidate("xai","x-ai/grok-voice-tts-1.0",{"host":"eve","analyst":"rex"},{"prompt":"0.000015","completion":"0"},"characters","calibration-20260722",("mp3",),("speech",),("response_format",),15000)
FALLBACK=Candidate("mistral","mistralai/voxtral-mini-tts-2603",{"host":"en_paul_neutral","analyst":"gb_jane_neutral"},{"prompt":"0.000016","completion":"0"},"characters","calibration-20260722",("mp3",),("speech",),("response_format",),4096)
MIN_DURATION=270; PREFERRED_DURATION=330; MAX_DURATION=390; DEFAULT_COST_CEILING=1.0
URL_RE=re.compile(r"(?:https?://|www\.)\S+",re.I); MARKDOWN_RE=re.compile(r"(?:^|\s)[#>*_`]|\[[^]]+\]\([^)]*\)")

class PodcastError(RuntimeError): pass
@dataclass(frozen=True)
class PodcastProfile:
 candidate:Candidate; fallback:Candidate|None; cost_ceiling:float=DEFAULT_COST_CEILING

def sha256(path:Path)->str:return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()
def podcast_key(publication_date:str,audio_sha256:str)->str:
 if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",publication_date) or not re.fullmatch(r"sha256:[0-9a-f]{64}",audio_sha256):raise PodcastError("podcast_key_invalid")
 return f"podcast/daily/{publication_date[:4]}/{publication_date[5:7]}/{publication_date[8:]}/{audio_sha256[7:]}.mp3"
def source_path(root:Path,publication_date:str)->Path:return root/"generated"/"editorial"/publication_date[:4]/f"{publication_date}.json"
def load_source(root:Path,publication_date:str)->tuple[dict[str,Any],str]:
 path=source_path(root,publication_date)
 if not path.is_file():raise PodcastError("source_daily_artifact_missing")
 doc=json.loads(path.read_text())
 if doc.get("date")!=publication_date or doc.get("status")!="ai_complete":raise PodcastError("source_daily_artifact_invalid")
 return doc,sha256(path)
def estimate_seconds(turns:list[dict[str,Any]])->int:return round(sum(len(t["text"]) for t in turns)/15.5+sum(t.get("pause_after_ms",0) for t in turns)/1000)
def expected_open_close(publication_date:str)->tuple[str,str]:
 return ("speaker_a","speaker_b") if date.fromisoformat(publication_date).day%2 else ("speaker_b","speaker_a")
def validate_script(script:dict[str,Any],source_sha256:str)->dict[str,Any]:
 required={"schema_version","publication_date","episode_title","summary","source_artifact_sha256","estimated_duration_seconds","speakers","turns"}
 if set(script)!=required or script["schema_version"]!="1.0.0" or script["source_artifact_sha256"]!=source_sha256:raise PodcastError("podcast_script_schema_invalid")
 turns=script["turns"]
 if not isinstance(turns,list) or len(turns)<12 or set(script["speakers"])!={"speaker_a","speaker_b"}:raise PodcastError("podcast_script_schema_invalid")
 opener,closer=expected_open_close(script["publication_date"])
 if turns[0].get("speaker")!=opener or turns[-1].get("speaker")!=closer:raise PodcastError("podcast_rotation_invalid")
 chars={"speaker_a":0,"speaker_b":0}; runs=0;previous=None; questions=set(); explained=set(); nuance=set()
 for i,t in enumerate(turns,1):
  if set(t)!={"turn_id","speaker","text","pause_after_ms"} or t["turn_id"]!=f"t{i:03}" or t["speaker"] not in chars or not isinstance(t["text"],str) or not t["text"].strip() or not isinstance(t["pause_after_ms"],int) or not 0<=t["pause_after_ms"]<=2000:raise PodcastError("podcast_turn_invalid")
  if URL_RE.search(t["text"]) or MARKDOWN_RE.search(t["text"]):raise PodcastError("podcast_spoken_markup_invalid")
  chars[t["speaker"]]+=len(t["text"]);runs=runs+1 if t["speaker"]==previous else 1;previous=t["speaker"]
  if runs>3:raise PodcastError("podcast_consecutive_turns_invalid")
  low=t["text"].lower()
  if "?" in t["text"]:questions.add(t["speaker"])
  if any(x in low for x in ("because","means","works","uses","happens when")):explained.add(t["speaker"])
  if any(x in low for x in ("but ","however","although","may ","could ","not necessarily")):nuance.add(t["speaker"])
 total=sum(chars.values()); shares={k:v/total for k,v in chars.items()} if total else {}
 if not all(.40<=x<=.60 for x in shares.values()) or questions!={"speaker_a","speaker_b"} or explained!={"speaker_a","speaker_b"} or nuance!={"speaker_a","speaker_b"}:raise PodcastError("podcast_balance_invalid")
 duration=estimate_seconds(turns)
 if not MIN_DURATION<=duration<=MAX_DURATION or abs(duration-script["estimated_duration_seconds"])>15:raise PodcastError("podcast_duration_invalid")
 return {"duration_seconds":duration,"characters":chars,"shares":shares,"turn_count":len(turns)}
def profile_from_args(use_fallback:bool,cost_ceiling:float)->PodcastProfile:
 if cost_ceiling<=0 or cost_ceiling>DEFAULT_COST_CEILING:raise PodcastError("podcast_cost_ceiling_invalid")
 return PodcastProfile(FALLBACK if use_fallback else DEFAULT,None if use_fallback else FALLBACK,cost_ceiling)
def estimate_cost(candidate:Candidate,characters:int)->float:return round(float(candidate.pricing["prompt"])*characters,6)
def preflight(root:Path,publication_date:str,use_fallback:bool,cost_ceiling:float)->dict[str,Any]:
 source,source_hash=load_source(root,publication_date);profile=profile_from_args(use_fallback,cost_ceiling)
 lead=source.get("plan",{}).get("lead",{})
 # 15.5 cps is intentionally conservative; long episodes are validated after editorial generation.
 target_chars=round(PREFERRED_DURATION*15.5);turns=24;maximum=estimate_cost(profile.candidate,target_chars)
 if maximum>cost_ceiling:raise PodcastError("podcast_estimated_cost_exceeds_ceiling")
 cap=CAPABILITIES[profile.candidate.model]
 return {"ready":True,"paid_calls":0,"publication_date":publication_date,"source_artifact":str(source_path(root,publication_date)),"source_artifact_sha256":source_hash,"source_lead":lead,"editorial_model":EDITORIAL_MODEL,"profile":PROFILE,"selected_model":profile.candidate.model,"voices":profile.candidate.voices,"fallback_model":profile.fallback.model if profile.fallback else None,"turns_planned":turns,"target_characters":target_chars,"estimated_duration_seconds":PREFERRED_DURATION,"estimated_maximum_cost_usd":maximum,"cost_ceiling_usd":cost_ceiling,"turn_format":cap["requested_format"],"output_directory":str(root/"generated"/"podcast"/publication_date[:4]),"r2_target_pattern":f"podcast/daily/{publication_date[:4]}/{publication_date[5:7]}/{publication_date[8:]}/<sha256>.mp3","frontend_publication_before_audio_validation":False,"cron_active":False}
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("command",choices=("preflight","generate"));p.add_argument("--date",required=True);p.add_argument("--publish",action="store_true");p.add_argument("--use-fallback",action="store_true");p.add_argument("--cost-ceiling",type=float,default=DEFAULT_COST_CEILING);p.add_argument("--authorize-paid",action="store_true");a=p.parse_args();root=Path.cwd();report=preflight(root,a.date,a.use_fallback,a.cost_ceiling);print(json.dumps(report,sort_keys=True,indent=2))
 if a.command=="preflight":return 0
 if not a.authorize_paid:raise PodcastError("explicit_paid_authorization_required")
 raise PodcastError("podcast_generation_requires_validated_script_and_authorized_release")
if __name__=="__main__":main()
