#!/usr/bin/env python3
"""Isolated blind TTS calibration; never imports production publication/storage code."""
from __future__ import annotations
import argparse,hashlib,json,os,secrets,shutil,subprocess,tempfile,time
from dataclasses import dataclass
from pathlib import Path
from typing import Any,Callable
import requests

MODELS_URL="https://openrouter.ai/api/v1/models?output_modalities=speech"
SPEECH_URL="https://openrouter.ai/api/v1/audio/speech"
TARGETS={"google":"google/gemini-3.1-flash-tts-preview","mistral":"mistralai/voxtral-mini-tts-2603"}
CHALLENGERS=("microsoft/mai-voice-2","x-ai/grok-voice-tts-1.0","deepgram/aura-2","canopylabs/orpheus-3b-0.1-ft","hexgrad/kokoro-82m")
# Versioned from current official OpenRouter model pages on 2026-07-22. Runtime
# model availability/pricing still comes exclusively from the Models API.
CAPABILITIES={
 "google/gemini-3.1-flash-tts-preview":{"provider":"google","host":"Kore","analyst":"Aoede","english_voices":{"Kore","Aoede","Charon","Orus"},"source":"https://openrouter.ai/google/gemini-3.1-flash-tts-preview","formats":{"mp3","pcm"},"pricing_unit":"mixed_tokens","speech_endpoint":True,"max_input":32768},
 "mistralai/voxtral-mini-tts-2603":{"provider":"mistral","host":"en_paul_neutral","analyst":"gb_jane_neutral","english_voices":{"en_paul_neutral","gb_oliver_neutral","gb_jane_neutral"},"source":"https://openrouter.ai/mistralai/voxtral-mini-tts-2603","formats":{"mp3","pcm"},"pricing_unit":"characters","speech_endpoint":True,"max_input":4096},
 "microsoft/mai-voice-2":{"provider":"microsoft","host":"en-US-Harper:MAI-Voice-2","analyst":None,"english_voices":{"en-US-Harper:MAI-Voice-2"},"source":"https://openrouter.ai/microsoft/mai-voice-2","formats":{"mp3","pcm"},"pricing_unit":"characters","speech_endpoint":True,"max_input":0},
 "x-ai/grok-voice-tts-1.0":{"provider":"xai","host":"eve","analyst":"rex","english_voices":{"eve","ara","rex","sal","leo"},"source":"https://openrouter.ai/x-ai/grok-voice-tts-1.0","formats":{"mp3","pcm"},"pricing_unit":"characters","speech_endpoint":True,"max_input":15000},
 "deepgram/aura-2":{"provider":"deepgram","host":"aura-2-thalia-en","analyst":"aura-2-apollo-en","english_voices":{"aura-2-thalia-en","aura-2-apollo-en"},"source":"https://openrouter.ai/deepgram/aura-2","formats":{"mp3","pcm"},"pricing_unit":"characters","speech_endpoint":True,"max_input":2000},
 "canopylabs/orpheus-3b-0.1-ft":{"provider":"canopylabs","host":"tara","analyst":"leo","english_voices":{"tara","leah","jess","leo","dan","mia","zac"},"source":"https://openrouter.ai/canopylabs/orpheus-3b-0.1-ft","formats":{"mp3","pcm"},"pricing_unit":"characters","speech_endpoint":True,"max_input":4096},
 "hexgrad/kokoro-82m":{"provider":"hexgrad","host":"af_heart","analyst":"am_adam","english_voices":{"af_heart","af_sarah","am_adam","am_michael"},"source":"https://openrouter.ai/hexgrad/kokoro-82m","formats":{"mp3","pcm"},"pricing_unit":"characters","speech_endpoint":True,"max_input":4096},
}

class CalibrationError(RuntimeError):pass
@dataclass(frozen=True)
class Candidate:
 provider:str;model:str;voices:dict[str,str];pricing:dict[str,str];pricing_unit:str;voice_metadata_source:str;formats:tuple[str,...];output_modalities:tuple[str,...];supported_parameters:tuple[str,...];max_input:int

def _candidate(model:dict[str,Any],max_turn_input:int)->Candidate|None:
 slug=model.get("id");cap=CAPABILITIES.get(slug);arch=model.get("architecture") or {};pricing=model.get("pricing") or {}
 if not cap or arch.get("modality")!="text->speech" or "speech" not in arch.get("output_modalities",[]) or not cap["speech_endpoint"] or not pricing.get("prompt") or cap["max_input"]<max_turn_input:return None
 voices=[cap.get("host"),cap.get("analyst")]
 try:validate_voices(cap,voices)
 except CalibrationError:return None
 return Candidate(cap["provider"],slug,{"host":voices[0],"analyst":voices[1]},dict(pricing),cap["pricing_unit"],cap["source"],tuple(sorted(cap["formats"])),tuple(arch.get("output_modalities",[])),tuple(model.get("supported_parameters") or []),cap["max_input"])

def discover_models(doc:dict[str,Any],max_turn_input:int=1)->tuple[list[Candidate],list[str]]:
 data=doc.get("data")
 if not isinstance(data,list):raise CalibrationError("models_response_invalid")
 by_id={m.get("id"):m for m in data if isinstance(m,dict)};selected=[];missing=[]
 for name in ("google","mistral"):
  candidate=_candidate(by_id.get(TARGETS[name],{}),max_turn_input)
  if candidate:selected.append(candidate)
  else:missing.append(name)
 challenger=next((c for slug in CHALLENGERS if (c:=_candidate(by_id.get(slug,{}),max_turn_input))),None)
 if challenger:selected.append(challenger)
 else:missing.append("challenger")
 return selected,missing

def validate_voices(profile:dict[str,Any],voices:list[str])->None:
 if len(voices)!=2 or voices[0]==voices[1] or any(not isinstance(v,str) or v not in profile["english_voices"] for v in voices):raise CalibrationError("unsupported_or_duplicate_voice")

def build_request(candidate:Candidate,turn:dict[str,Any])->dict[str,Any]:
 speaker=turn.get("speaker");
 if speaker not in ("host","analyst") or not isinstance(turn.get("text"),str) or not turn["text"].strip():raise CalibrationError("turn_invalid")
 return {"model":candidate.model,"input":turn["text"],"voice":candidate.voices[speaker],"response_format":"mp3"}

def build_gemini_bonus(candidate:Candidate,turns:list[dict[str,Any]])->dict[str,Any]:
 if candidate.model!=TARGETS["google"]:raise CalibrationError("bonus_requires_gemini")
 lines=[f"{'Host' if x['speaker']=='host' else 'Analyst'}: {x['text']}" for x in turns]
 return {"model":candidate.model,"input":"\n\n".join(lines),"voice":candidate.voices["host"],"response_format":"mp3","provider":{"options":{"google-vertex":{"speech_config":{"multi_speaker_voice_config":{"speaker_voice_configs":[{"speaker":"Host","voice_config":{"prebuilt_voice_config":{"voice_name":candidate.voices['host']}}},{"speaker":"Analyst","voice_config":{"prebuilt_voice_config":{"voice_name":candidate.voices['analyst']}}}]}}}}}}

def validate_audio_response(response:Any)->bytes:
 content=bytes(response.content);ctype=str(response.headers.get("content-type","")).split(";",1)[0].lower()
 if response.status_code<200 or response.status_code>=300:raise CalibrationError(f"speech_http_{response.status_code}")
 if ctype not in ("audio/mpeg","audio/mp3","application/octet-stream") or content.lstrip().startswith((b"{",b"[")):raise CalibrationError("speech_response_not_audio")
 if len(content)<64:raise CalibrationError("speech_response_too_small")
 return content

def generation_id(response:Any)->str|None:
 value=response.headers.get("x-generation-id") or response.headers.get("X-Generation-Id");return value[:256] if isinstance(value,str) and value else None

def request_turn(post:Callable[...,Any],key:str,body:dict[str,Any],max_retries:int=1)->tuple[bytes,dict[str,Any]]:
 if max_retries not in (0,1):raise CalibrationError("retry_bound_invalid")
 last=None
 for retry in range(max_retries+1):
  started=time.monotonic()
  try:r=post(SPEECH_URL,headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},json=body,timeout=180);audio=validate_audio_response(r);return audio,{"http_status":r.status_code,"content_type":r.headers.get("content-type"),"generation_id":generation_id(r),"bytes":len(audio),"duration_ms":round((time.monotonic()-started)*1000),"retry_count":retry}
  except (requests.RequestException,CalibrationError) as exc:
   last=exc
   if retry>=max_retries or isinstance(exc,CalibrationError) and str(exc).startswith("speech_http_4"):raise
 raise last or CalibrationError("speech_failed")

def secure_mapping(candidates:list[Candidate])->dict[str,Candidate]:
 shuffled=list(candidates);secrets.SystemRandom().shuffle(shuffled);return dict(zip(("candidate-a","candidate-b","candidate-c"),shuffled,strict=True))

def write_reveal(path:Path,mapping:dict[str,Candidate],records:dict[str,list[dict[str,Any]]]|None=None)->None:
 path.write_text(json.dumps({"mapping":{k:{"provider":v.provider,"model":v.model,"voices":v.voices} for k,v in mapping.items()},"generation_records":records or {}},sort_keys=True,indent=2)+"\n");os.chmod(path,0o600)

def assemble(turn_files:list[Path],pauses:list[int],output:Path,run:Callable[...,Any]=subprocess.run)->None:
 if len(turn_files)!=len(pauses) or not turn_files:raise CalibrationError("assembly_order_invalid")
 with tempfile.TemporaryDirectory(prefix="tldr-tts-assemble-") as td:
  parts=[]
  for i,(source,pause) in enumerate(zip(turn_files,pauses,strict=True)):
   normalized=Path(td)/f"turn-{i:02}.mp3";run(["ffmpeg","-v","error","-y","-i",str(source),"-ar","44100","-ac","1","-map_metadata","-1",str(normalized)],check=True);parts.append(normalized)
   if pause:
    silence=Path(td)/f"pause-{i:02}.mp3";run(["ffmpeg","-v","error","-y","-f","lavfi","-i","anullsrc=r=44100:cl=mono","-t",f"{pause/1000:.3f}","-map_metadata","-1",str(silence)],check=True);parts.append(silence)
  listing=Path(td)/"concat.txt";listing.write_text("".join(f"file '{p}'\n" for p in parts));run(["ffmpeg","-v","error","-y","-f","concat","-safe","0","-i",str(listing),"-ar","44100","-ac","1","-map_metadata","-1",str(output)],check=True)

def probe(path:Path,run:Callable[...,Any]=subprocess.run)->dict[str,Any]:
 r=run(["ffprobe","-v","error","-show_entries","format=duration:format_tags","-of","json",str(path)],capture_output=True,text=True,check=True);doc=json.loads(r.stdout);tags=doc.get("format",{}).get("tags") or {};return {"duration_seconds":round(float(doc["format"]["duration"]),3),"bytes":path.stat().st_size,"sha256":"sha256:"+hashlib.sha256(path.read_bytes()).hexdigest(),"metadata_tags":tags}

def estimate(candidates:list[Candidate],characters:int,audio_seconds_upper:int=90,include_bonus:bool=True)->dict[str,Any]:
 rows=[];audio_tokens=audio_seconds_upper*32;text_tokens=(characters+2)//3
 for c in candidates:
  if c.pricing_unit=="characters":cost=float(c.pricing["prompt"])*characters;basis={"characters":characters,"price_per_character":c.pricing["prompt"]}
  elif c.pricing_unit=="mixed_tokens":cost=float(c.pricing["prompt"])*text_tokens+float(c.pricing["completion"])*audio_tokens;basis={"estimated_text_tokens":text_tokens,"text_token_price":c.pricing["prompt"],"estimated_audio_tokens":audio_tokens,"audio_token_price":c.pricing["completion"],"method":"ceil(characters/3) text tokens plus 32 audio tokens/second for 90 seconds"}
  else:raise CalibrationError("pricing_unit_unsupported")
  rows.append({"model":c.model,"pricing_unit":c.pricing_unit,"estimated_cost_usd":round(cost,6),**basis,"per_request_minimum":None})
 main=round(sum(x["estimated_cost_usd"] for x in rows),6);google=next((x for x in rows if x["model"]==TARGETS["google"]),None);bonus=google["estimated_cost_usd"] if include_bonus and google else 0
 return {"candidates":rows,"main_cost_upper_bound_usd":main,"gemini_bonus_cost_upper_bound_usd":bonus,"total_upper_bound_usd":round(main+bonus,6),"audio_seconds_upper_bound":audio_seconds_upper}

def paid_gate(*,authorized:bool,candidates:list[Candidate],estimated_total:float,output:Path,bonus:bool=False,bonus_authorized:bool=False)->None:
 if not authorized:raise CalibrationError("explicit_paid_authorization_required")
 if len(candidates)!=3:raise CalibrationError("three_candidates_required")
 if bonus and not bonus_authorized:raise CalibrationError("separate_bonus_authorization_required")
 if estimated_total>1:raise CalibrationError("estimated_cost_exceeds_limit")
 if not os.getenv("OPENROUTER_API_KEY"):raise CalibrationError("openrouter_key_missing")
 if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):raise CalibrationError("ffmpeg_missing")
 if output.resolve().is_relative_to(Path.cwd().resolve()):raise CalibrationError("output_must_be_outside_repository")
 if subprocess.run(["git","status","--porcelain"],capture_output=True,text=True,check=True).stdout:raise CalibrationError("working_tree_dirty")

def dialogue(path:Path)->dict[str,Any]:
 d=json.loads(path.read_text());turns=d.get("turns");
 if d.get("schema_version")!="1.0.0" or d.get("language")!="en-US" or not isinstance(turns,list) or [x.get("turn_id") for x in turns]!=[f"t{i:02}" for i in range(1,len(turns)+1)]:raise CalibrationError("dialogue_invalid")
 return d

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("command",choices=("preflight","generate"));p.add_argument("--dialogue",type=Path,default=Path("calibration/tts/blind-test-v1/dialogue.json"));p.add_argument("--output",type=Path,required=True);p.add_argument("--authorize-paid",action="store_true");p.add_argument("--include-gemini-bonus",action="store_true");p.add_argument("--authorize-bonus-paid",action="store_true");a=p.parse_args();key=os.getenv("OPENROUTER_API_KEY")
 if not key:raise CalibrationError("openrouter_key_missing")
 d=dialogue(a.dialogue);chars=sum(len(x["text"]) for x in d["turns"]);max_turn=max(len(x["text"]) for x in d["turns"]);doc=requests.get(MODELS_URL,headers={"Authorization":"Bearer "+key},timeout=30).json();candidates,missing=discover_models(doc,max_turn);cost=estimate(candidates,chars);report={"models":[{"model":x.model,"provider":x.provider,"voices":x.voices,"voice_metadata_source":x.voice_metadata_source,"output_modalities":x.output_modalities,"pricing":x.pricing,"pricing_unit":x.pricing_unit,"supported_parameters":x.supported_parameters,"max_input":x.max_input,"formats":x.formats,"speed_supported":False} for x in candidates],"missing_candidates":missing,"turns":len(d["turns"]),"fair_test_requests":len(d["turns"])*len(candidates),"bonus_requests":1,"characters_per_candidate":chars,"fair_test_input_characters":chars*len(candidates),"bonus_input_characters":chars,"estimated_cost":cost,"output":str(a.output),"production_writes":0,"r2_calls":0,"frontend_writes":0,"paid_calls":0,"ready":len(candidates)==3 and cost["total_upper_bound_usd"]<1}
 print(json.dumps(report,indent=2,sort_keys=True))
 if a.command=="preflight":return 0 if report["ready"] else 2
 paid_gate(authorized=a.authorize_paid,candidates=candidates,estimated_total=cost["total_upper_bound_usd"] if a.include_gemini_bonus else cost["main_cost_upper_bound_usd"],output=a.output,bonus=a.include_gemini_bonus,bonus_authorized=a.authorize_bonus_paid);a.output.mkdir(parents=True,exist_ok=False,mode=0o700);mapping=secure_mapping(candidates);records={};public=[];dialogue_hash="sha256:"+hashlib.sha256(a.dialogue.read_bytes()).hexdigest()
 for anonymous,candidate in mapping.items():
  private=a.output/("."+anonymous+"-turns");private.mkdir(mode=0o700);files=[];records[anonymous]=[]
  for turn in d["turns"]:
   body=build_request(candidate,turn);audio,meta=request_turn(requests.post,key,body,max_retries=1);path=private/(turn["turn_id"]+".mp3");path.write_bytes(audio);os.chmod(path,0o600);files.append(path);records[anonymous].append({**meta,"turn_id":turn["turn_id"],"model":candidate.model,"voice":body["voice"]})
  final=a.output/(anonymous+".mp3");assemble(files,[x["pause_after_ms"] for x in d["turns"]],final);info=probe(final);public.append({"candidate_id":anonymous,"ranking_eligible":True,"file":final.name,**{k:info[k] for k in ("duration_seconds","bytes","sha256")},"dialogue_sha256":dialogue_hash,"generated_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())});shutil.rmtree(private)
 if a.include_gemini_bonus:
  gemini=next(x for x in candidates if x.model==TARGETS["google"]);body=build_gemini_bonus(gemini,d["turns"]);audio,meta=request_turn(requests.post,key,body,max_retries=1);raw=a.output/".bonus-raw.mp3";raw.write_bytes(audio);final=a.output/"candidate-bonus.mp3";assemble([raw],[0],final);raw.unlink();info=probe(final);records["candidate-bonus"]=[{**meta,"turn_id":"native-dialogue","model":gemini.model,"voices":gemini.voices,"provider_options":body["provider"]}];public.append({"candidate_id":"candidate-bonus","ranking_eligible":False,"label":"Experimental cohesive-dialogue bonus — not part of the main ranking.","file":final.name,**{k:info[k] for k in ("duration_seconds","bytes","sha256")},"dialogue_sha256":dialogue_hash,"generated_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())})
 write_reveal(a.output/"tts-reveal.json",mapping,records);manifest={"schema_version":"1.0.0","dialogue_sha256":dialogue_hash,"candidates":public};(a.output/"manifest.public.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n");shutil.copy2(Path("calibration/tts/blind-test-v1/evaluation.md"),a.output/"evaluation.md");print(json.dumps({"generated":len(public),"output":str(a.output),"paid_requests":sum(len(x) for x in records.values())},sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
