#!/usr/bin/env python3
"""Isolated blind TTS calibration; never imports production publication/storage code."""
from __future__ import annotations
import argparse,hashlib,json,os,re,secrets,shutil,subprocess,tempfile,time
from dataclasses import dataclass
from pathlib import Path
from typing import Any,Callable
import requests

MODELS_URL="https://openrouter.ai/api/v1/models?output_modalities=speech"
SPEECH_URL="https://openrouter.ai/api/v1/audio/speech"
GEMINI_BONUS_SUPPORTED=False
GEMINI_BONUS_REASON="OpenRouter documents generic provider options but not the Gemini multi_speaker_voice_config speech payload"
TARGETS={"google":"google/gemini-3.1-flash-tts-preview","mistral":"mistralai/voxtral-mini-tts-2603"}
CHALLENGERS=("microsoft/mai-voice-2","x-ai/grok-voice-tts-1.0","deepgram/aura-2","canopylabs/orpheus-3b-0.1-ft","hexgrad/kokoro-82m")
# Versioned from current official OpenRouter model pages on 2026-07-22. Runtime
# model availability/pricing still comes exclusively from the Models API.
CAPABILITIES={
 "google/gemini-3.1-flash-tts-preview":{"provider":"google","host":"Kore","analyst":"Aoede","english_voices":{"Kore","Aoede","Charon","Orus"},"source":"https://openrouter.ai/google/gemini-3.1-flash-tts-preview","formats":{"pcm"},"requested_format":"pcm","accepted_mime":"audio/pcm;rate=24000;channels=1","native_codec":"pcm_s16le","sample_rate":24000,"channels":1,"transcoded":False,"speed":False,"provider_passthrough":False,"canary_proven":True,"pricing_unit":"mixed_tokens","speech_endpoint":True,"max_input":32768},
 "mistralai/voxtral-mini-tts-2603":{"provider":"mistral","host":"en_paul_neutral","analyst":"gb_jane_neutral","english_voices":{"en_paul_neutral","gb_oliver_neutral","gb_jane_neutral"},"source":"https://openrouter.ai/mistralai/voxtral-mini-tts-2603","formats":{"mp3"},"requested_format":"mp3","accepted_mime":"audio/mpeg","native_codec":"mp3","sample_rate":22050,"channels":1,"transcoded":None,"speed":False,"provider_passthrough":False,"host_canary_proven":True,"analyst_voice_metadata_validated":True,"analyst_canary_proven":False,"canary_proven":True,"pricing_unit":"characters","speech_endpoint":True,"max_input":4096},
 "microsoft/mai-voice-2":{"provider":"microsoft","host":"en-US-Harper:MAI-Voice-2","analyst":None,"english_voices":{"en-US-Harper:MAI-Voice-2"},"source":"https://openrouter.ai/microsoft/mai-voice-2","formats":{"mp3","pcm"},"pricing_unit":"characters","speech_endpoint":True,"max_input":0},
 "x-ai/grok-voice-tts-1.0":{"provider":"xai","host":"eve","analyst":"rex","english_voices":{"eve","ara","rex","sal","leo"},"source":"https://openrouter.ai/x-ai/grok-voice-tts-1.0","formats":{"mp3"},"requested_format":"mp3","accepted_mime":"audio/mpeg","native_codec":"mp3","sample_rate":24000,"channels":1,"transcoded":None,"speed":False,"provider_passthrough":False,"host_canary_proven":True,"analyst_voice_metadata_validated":True,"analyst_canary_proven":True,"canary_proven":True,"pricing_unit":"characters","speech_endpoint":True,"max_input":15000},
 "deepgram/aura-2":{"provider":"deepgram","host":"aura-2-thalia-en","analyst":"aura-2-apollo-en","english_voices":{"aura-2-thalia-en","aura-2-apollo-en"},"source":"https://openrouter.ai/deepgram/aura-2","formats":{"mp3","pcm"},"pricing_unit":"characters","speech_endpoint":True,"max_input":2000},
 "canopylabs/orpheus-3b-0.1-ft":{"provider":"canopylabs","host":"tara","analyst":"leo","english_voices":{"tara","leah","jess","leo","dan","mia","zac"},"source":"https://openrouter.ai/canopylabs/orpheus-3b-0.1-ft","formats":{"mp3","pcm"},"pricing_unit":"characters","speech_endpoint":True,"max_input":4096},
 "hexgrad/kokoro-82m":{"provider":"hexgrad","host":"af_heart","analyst":"am_adam","english_voices":{"af_heart","af_sarah","am_adam","am_michael"},"source":"https://openrouter.ai/hexgrad/kokoro-82m","formats":{"mp3","pcm"},"pricing_unit":"characters","speech_endpoint":True,"max_input":4096},
}

class CalibrationError(RuntimeError):pass
class SpeechHTTPError(CalibrationError):
 def __init__(self,status:int,diagnostic:dict[str,Any]):super().__init__(f"speech_http_{status}: {diagnostic.get('error_message') or 'request rejected'}");self.status=status;self.diagnostic=diagnostic

def _private_json(directory:Path,name:str,value:dict[str,Any])->Path:
 directory.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(directory,0o700);path=directory/name;path.write_text(json.dumps(value,sort_keys=True,indent=2,ensure_ascii=False)+"\n");os.chmod(path,0o600);return path

def _redact(text:str,secrets_to_hide:tuple[str,...])->str:
 out=text
 for secret in secrets_to_hide:
  if secret:out=out.replace(secret,"[REDACTED]")
 out=re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+",r"\1[REDACTED]",out);out=re.sub(r"(?i)(api[_-]?key[\"' :=]+)[^\s\"']+",r"\1[REDACTED]",out);return out

def http_diagnostic(response:Any,body:dict[str,Any],turn_id:str,attempt:int,key:str)->dict[str,Any]:
 raw=bytes(response.content);bounded=raw[:16384];text=_redact(bounded.decode("utf-8",errors="replace"),(key,));text=text.encode("utf-8")[:16384].decode("utf-8",errors="ignore");parsed=None;code=message=None
 try:parsed=json.loads(text)
 except (TypeError,json.JSONDecodeError):pass
 if isinstance(parsed,dict):
  error=parsed.get("error")
  if isinstance(error,dict):code=error.get("code");message=error.get("message")
 safe_headers={k.lower():v for k,v in response.headers.items() if k.lower() in {"content-type","x-generation-id","x-request-id","x-openrouter-request-id"}}
 return {"http_status":response.status_code,"content_type":response.headers.get("content-type"),"safe_response_headers":safe_headers,"response_body":text,"response_body_truncated":len(raw)>16384,"error_code":str(code)[:256] if code is not None else None,"error_message":_redact(str(message)[:1000],(key,)) if message is not None else None,"model":body.get("model"),"voice":body.get("voice"),"response_format":body.get("response_format"),"turn_id":turn_id,"attempt_number":attempt,"input_sha256":"sha256:"+hashlib.sha256(str(body.get("input","")).encode()).hexdigest(),"input_characters":len(str(body.get("input","")))}
@dataclass(frozen=True)
class Candidate:
 provider:str;model:str;voices:dict[str,str];pricing:dict[str,str];pricing_unit:str;voice_metadata_source:str;formats:tuple[str,...];output_modalities:tuple[str,...];supported_parameters:tuple[str,...];max_input:int

@dataclass(frozen=True)
class TurnDescriptor:
 path:Path;codec:str;sample_rate:int;channels:int;raw:bool;candidate_id:str;turn_id:str;requested_format:str;received_mime:str

@dataclass
class AttemptBudget:
 logical_requests_planned:int=24;max_total_attempts:int=24;http_attempts:int=0;successful_responses:int=0;validated_turns:int=0;failed_attempts:int=0
 def claim(self)->None:
  if self.http_attempts>=self.max_total_attempts:raise CalibrationError("attempt_budget_exhausted")
  self.http_attempts+=1
 def succeeded(self)->None:self.successful_responses+=1
 def validated(self)->None:self.validated_turns+=1
 def failed(self)->None:self.failed_attempts+=1
 def snapshot(self)->dict[str,int]:return {"logical_requests_planned":self.logical_requests_planned,"max_total_attempts":self.max_total_attempts,"http_attempts":self.http_attempts,"successful_responses":self.successful_responses,"validated_turns":self.validated_turns,"failed_attempts":self.failed_attempts,"remaining_attempt_budget":self.max_total_attempts-self.http_attempts,"retries":0}

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
 format=CAPABILITIES[candidate.model].get("requested_format")
 if not format:raise CalibrationError("model_canary_not_proven")
 return {"model":candidate.model,"input":turn["text"],"voice":candidate.voices[speaker],"response_format":format}

def build_gemini_bonus(candidate:Candidate,turns:list[dict[str,Any]])->dict[str,Any]:
 raise CalibrationError("gemini_bonus_contract_unproven")

def validate_audio_response(response:Any)->bytes:
 content=bytes(response.content);ctype=str(response.headers.get("content-type","")).split(";",1)[0].lower()
 if response.status_code<200 or response.status_code>=300:raise CalibrationError(f"speech_http_{response.status_code}")
 if ctype not in ("audio/mpeg","audio/mp3","audio/pcm","audio/wav","audio/x-wav","application/octet-stream") or content.lstrip().startswith((b"{",b"[")):raise CalibrationError("speech_response_not_audio")
 if len(content)<64:raise CalibrationError("speech_response_too_small")
 return content

def generation_id(response:Any)->str|None:
 value=response.headers.get("x-generation-id") or response.headers.get("X-Generation-Id");return value[:256] if isinstance(value,str) and value else None

def request_turn(post:Callable[...,Any],key:str,body:dict[str,Any],max_retries:int=1,*,turn_id:str="unknown",diagnostic_dir:Path|None=None)->tuple[bytes,dict[str,Any]]:
 if max_retries not in (0,1):raise CalibrationError("retry_bound_invalid")
 last=None
 for retry in range(max_retries+1):
  started=time.monotonic()
  try:
   r=post(SPEECH_URL,headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},json=body,timeout=180)
   if not 200<=r.status_code<300:
    diagnostic=http_diagnostic(r,body,turn_id,retry+1,key)
    if diagnostic_dir:_private_json(diagnostic_dir,f"http-error-{turn_id}-attempt-{retry+1}.json",diagnostic)
    raise SpeechHTTPError(r.status_code,diagnostic)
   audio=validate_audio_response(r);return audio,{"http_status":r.status_code,"content_type":r.headers.get("content-type"),"generation_id":generation_id(r),"bytes":len(audio),"duration_ms":round((time.monotonic()-started)*1000),"retry_count":retry}
  except (requests.RequestException,CalibrationError) as exc:
   last=exc
   if retry>=max_retries or isinstance(exc,SpeechHTTPError) and 400<=exc.status<500:raise
 raise last or CalibrationError("speech_failed")

def secure_mapping(candidates:list[Candidate])->dict[str,Candidate]:
 shuffled=list(candidates);secrets.SystemRandom().shuffle(shuffled);return dict(zip(("candidate-a","candidate-b","candidate-c"),shuffled,strict=True))

def write_reveal(path:Path,mapping:dict[str,Candidate],records:dict[str,list[dict[str,Any]]]|None=None)->None:
 path.write_text(json.dumps({"mapping":{k:{"provider":v.provider,"model":v.model,"voices":v.voices} for k,v in mapping.items()},"generation_records":records or {}},sort_keys=True,indent=2)+"\n");os.chmod(path,0o600)

def turn_descriptor(candidate:Candidate,candidate_id:str,turn_id:str,directory:Path,received_mime:str)->TurnDescriptor:
 cap=CAPABILITIES[candidate.model];format=cap["requested_format"]
 if format=="pcm":return TurnDescriptor(directory/f"{turn_id}.pcm","pcm_s16le",cap["sample_rate"],cap["channels"],True,candidate_id,turn_id,format,received_mime)
 if format=="mp3":return TurnDescriptor(directory/f"{turn_id}.mp3","mp3",cap["sample_rate"],cap["channels"],False,candidate_id,turn_id,format,received_mime)
 raise CalibrationError("turn_format_unproven")

def decoder_args(turn:TurnDescriptor)->list[str]:
 return ["-f","s16le","-ar",str(turn.sample_rate),"-ac",str(turn.channels),"-i",str(turn.path)] if turn.raw else ["-i",str(turn.path)]

def validate_turn(turn:TurnDescriptor,run:Callable[...,Any]=subprocess.run)->dict[str,Any]:
 size=turn.path.stat().st_size;expected=f"audio/pcm;rate={turn.sample_rate};channels={turn.channels}" if turn.raw else "audio/mpeg"
 if turn.received_mime!=expected:raise CalibrationError("turn_mime_mismatch")
 if turn.raw:
  if size<=0 or size%2:raise CalibrationError("pcm_byte_count_invalid")
  duration=size/(turn.sample_rate*turn.channels*2)
  if duration<.1:raise CalibrationError("turn_audio_too_short")
  run(["ffmpeg","-v","error",*decoder_args(turn),"-f","null","-"],check=True)
 else:
  r=run(["ffprobe","-v","error","-show_entries","stream=codec_name,sample_rate,channels:format=duration","-of","json",str(turn.path)],capture_output=True,text=True,check=True);doc=json.loads(r.stdout);stream=doc["streams"][0];duration=float(doc["format"]["duration"])
  if stream["codec_name"]!="mp3" or int(stream["sample_rate"])!=turn.sample_rate or int(stream["channels"])!=turn.channels or duration<.1:raise CalibrationError("mp3_validation_failed")
 return {"duration_seconds":round(duration,6),"bytes":size,"codec":turn.codec,"sample_rate":turn.sample_rate,"channels":turn.channels}

def assemble(turns:list[TurnDescriptor],pauses:list[int],output:Path,run:Callable[...,Any]=subprocess.run)->None:
 if len(turns)!=len(pauses) or not turns:raise CalibrationError("assembly_order_invalid")
 with tempfile.TemporaryDirectory(prefix="tldr-tts-assemble-") as td:
  parts=[]
  for i,(turn,pause) in enumerate(zip(turns,pauses,strict=True)):
   normalized=Path(td)/f"turn-{i:02}.wav";run(["ffmpeg","-v","error","-y",*decoder_args(turn),"-c:a","pcm_s16le","-ar","24000","-ac","1","-map_metadata","-1",str(normalized)],check=True);parts.append(normalized)
   if pause:
    silence=Path(td)/f"pause-{i:02}.wav";run(["ffmpeg","-v","error","-y","-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t",f"{pause/1000:.3f}","-c:a","pcm_s16le","-map_metadata","-1",str(silence)],check=True);parts.append(silence)
  listing=Path(td)/"concat.txt";listing.write_text("".join(f"file '{p}'\n" for p in parts));temporary=output.with_name("."+output.name+".tmp.mp3");run(["ffmpeg","-v","error","-y","-f","concat","-safe","0","-i",str(listing),"-ar","24000","-ac","1","-c:a","libmp3lame","-b:a","128k","-map_metadata","-1",str(temporary)],check=True);os.replace(temporary,output)

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

def fair_execution_contract(candidates:list[Candidate],turn_count:int,retries:int=0,max_attempts:int=24)->dict[str,Any]:
 logical=len(candidates)*turn_count
 if len(candidates)!=3 or turn_count!=8 or logical!=24 or retries!=0 or max_attempts!=24:raise CalibrationError("fair_execution_contract_invalid")
 rows=[]
 for c in candidates:
  cap=CAPABILITIES[c.model];format=cap.get("requested_format");raw=format=="pcm";extension=".pcm" if raw else ".mp3"
  if raw and (cap.get("native_codec")!="pcm_s16le" or cap.get("sample_rate")!=24000 or cap.get("channels")!=1):raise CalibrationError("gemini_decoder_metadata_missing")
  rows.append({"model":c.model,"requested_response_format":format,"expected_mime":cap.get("accepted_mime"),"local_turn_extension":extension,"raw":raw,"decoder_arguments":["-f","s16le","-ar","24000","-ac","1"] if raw else [],"intermediate":{"container":"wav","codec":"pcm_s16le","sample_rate":24000,"channels":1},"final":{"container":"mp3","codec":"libmp3lame","sample_rate":24000,"channels":1,"bitrate":"128k"}})
 return {"candidates":rows,"logical_requests":logical,"maximum_http_attempts":max_attempts,"retries":retries}

def paid_gate(*,authorized:bool,candidates:list[Candidate],estimated_total:float,output:Path,bonus:bool=False,bonus_authorized:bool=False)->None:
 if not authorized:raise CalibrationError("explicit_paid_authorization_required")
 if len(candidates)!=3:raise CalibrationError("three_candidates_required")
 if not all(CAPABILITIES[x.model].get("canary_proven") for x in candidates):raise CalibrationError("all_three_canaries_required")
 if bonus and not GEMINI_BONUS_SUPPORTED:raise CalibrationError("gemini_bonus_contract_unproven")
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
 d=dialogue(a.dialogue);chars=sum(len(x["text"]) for x in d["turns"]);max_turn=max(len(x["text"]) for x in d["turns"]);doc=requests.get(MODELS_URL,headers={"Authorization":"Bearer "+key},timeout=30).json();candidates,missing=discover_models(doc,max_turn);cost=estimate(candidates,chars);contract=fair_execution_contract(candidates,len(d["turns"]),0,24);ready=len(candidates)==3 and all(CAPABILITIES[x.model].get("canary_proven") for x in candidates) and cost["main_cost_upper_bound_usd"]<1
 report={"models":[{"model":x.model,"provider":x.provider,"voices":x.voices,"requested_format":CAPABILITIES[x.model]["requested_format"],"accepted_mime":CAPABILITIES[x.model]["accepted_mime"]} for x in candidates],"missing_candidates":missing,"turns":len(d["turns"]),"fair_execution_contract":contract,"bonus_requests":0,"bonus_supported":False,"characters_per_candidate":chars,"estimated_cost":cost,"output":str(a.output),"production_writes":0,"r2_calls":0,"frontend_writes":0,"paid_calls":0,"ready":ready}
 print(json.dumps(report,indent=2,sort_keys=True))
 if a.command=="preflight":return 0 if ready else 2
 if a.include_gemini_bonus or a.authorize_bonus_paid:raise CalibrationError("gemini_bonus_contract_unproven")
 paid_gate(authorized=a.authorize_paid,candidates=candidates,estimated_total=cost["main_cost_upper_bound_usd"],output=a.output);a.output.mkdir(parents=True,exist_ok=False,mode=0o700);mapping=secure_mapping(candidates);records={};write_reveal(a.output/"tts-reveal.json",mapping,records);budget=AttemptBudget();_private_json(a.output,"run-state.json",{"status":"incomplete",**budget.snapshot()});public=[];assembled={};dialogue_hash="sha256:"+hashlib.sha256(a.dialogue.read_bytes()).hexdigest()
 for anonymous,candidate in mapping.items():
  private=a.output/("."+anonymous+"-turns");private.mkdir(mode=0o700);descriptors=[];records[anonymous]=[]
  for turn in d["turns"]:
   body=build_request(candidate,turn);budget.claim();_private_json(a.output,"run-state.json",{"status":"incomplete",**budget.snapshot()})
   try:audio,meta=request_turn(requests.post,key,body,max_retries=0,turn_id=turn["turn_id"],diagnostic_dir=a.output/"diagnostics")
   except Exception:
    budget.failed();_private_json(a.output,"run-state.json",{"status":"failed",**budget.snapshot()});raise
   budget.succeeded();descriptor=turn_descriptor(candidate,anonymous,turn["turn_id"],private,meta["content_type"]);descriptor.path.write_bytes(audio);os.chmod(descriptor.path,0o600)
   sidecar={"path":descriptor.path.name,"codec":descriptor.codec,"sample_rate":descriptor.sample_rate,"channels":descriptor.channels,"container":"raw" if descriptor.raw else "mp3","candidate_id":anonymous,"turn_id":turn["turn_id"],"requested_response_format":descriptor.requested_format,"received_mime_type":descriptor.received_mime};_private_json(private,turn["turn_id"]+".json",sidecar)
   try:validation=validate_turn(descriptor)
   except Exception:
    _private_json(a.output,"run-state.json",{"status":"failed_validation",**budget.snapshot()});raise
   budget.validated();descriptors.append(descriptor);records[anonymous].append({**meta,**sidecar,"validation":validation,"model":candidate.model,"voice":body["voice"]});write_reveal(a.output/"tts-reveal.json",mapping,records);_private_json(a.output,"run-state.json",{"status":"incomplete",**budget.snapshot()})
  hidden=a.output/(".assembled-"+anonymous+".mp3");assemble(descriptors,[x["pause_after_ms"] for x in d["turns"]],hidden);assembled[anonymous]=hidden;info=probe(hidden);public.append({"candidate_id":anonymous,"ranking_eligible":True,"file":anonymous+".mp3",**{k:info[k] for k in ("duration_seconds","bytes","sha256")},"dialogue_sha256":dialogue_hash,"generated_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())})
 if budget.http_attempts!=24 or budget.successful_responses!=24 or budget.validated_turns!=24:raise CalibrationError("fair_run_incomplete")
 for anonymous,hidden in assembled.items():os.replace(hidden,a.output/(anonymous+".mp3"))
 write_reveal(a.output/"tts-reveal.json",mapping,records);manifest={"schema_version":"1.0.0","dialogue_sha256":dialogue_hash,"candidates":public};temporary=a.output/".manifest.public.json.tmp";temporary.write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n");os.replace(temporary,a.output/"manifest.public.json");shutil.copy2(Path("calibration/tts/blind-test-v1/evaluation.md"),a.output/"evaluation.md");_private_json(a.output,"run-state.json",{"status":"complete",**budget.snapshot()});print(json.dumps({"generated":3,"output":str(a.output),**budget.snapshot()},sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
