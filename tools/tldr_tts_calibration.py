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
TARGETS={"openai":"openai/gpt-4o-mini-tts-2025-12-15","mistral":"mistralai/voxtral-mini-tts-2603"}
VOICE_PROFILES={
 "openai":{"host":"alloy","analyst":"nova","voices":{"alloy","ash","ballad","coral","echo","fable","nova","onyx","sage","shimmer","verse"},"formats":{"mp3","opus","aac","flac","wav","pcm"},"speed":True,"instructions":True},
 "google":{"host":"Kore","analyst":"Aoede","voices":{"Zephyr","Puck","Charon","Kore","Fenrir","Leda","Orus","Aoede","Callirrhoe","Autonoe","Enceladus","Iapetus","Umbriel","Algieba","Despina","Erinome","Algenib","Rasalgethi","Laomedeia","Achernar","Alnilam","Schedar","Gacrux","Pulcherrima","Achird","Zubenelgenubi","Vindemiatrix","Sadachbia","Sadaltager","Sulafat"},"formats":{"mp3","wav","pcm"},"speed":True,"instructions":False},
 "mistral":{"host":"en_paul_neutral","analyst":"gb_jane_neutral","voices":{"en_paul_neutral","gb_oliver_neutral","gb_jane_neutral"},"formats":{"mp3","wav","pcm"},"speed":True,"instructions":False},
}
DELIVERY="Speak naturally as part of a calm, informed technology-news conversation. Avoid advertising cadence, exaggerated enthusiasm, and theatrical delivery."

class CalibrationError(RuntimeError):pass
@dataclass(frozen=True)
class Candidate:
 provider:str;model:str;voices:dict[str,str];pricing:dict[str,str];output_modalities:tuple[str,...];supported_parameters:tuple[str,...];context_length:int|None

def discover_models(doc:dict[str,Any])->tuple[list[Candidate],list[str]]:
 data=doc.get("data");
 if not isinstance(data,list):raise CalibrationError("models_response_invalid")
 speech=[m for m in data if isinstance(m,dict) and m.get("architecture",{}).get("modality")=="text->speech" and "speech" in m.get("architecture",{}).get("output_modalities",[])]
 by_id={m.get("id"):m for m in speech};google=sorted((m for m in speech if str(m.get("id","")).startswith("google/gemini-") and "flash" in m["id"] and "tts" in m["id"]),key=lambda x:x["id"],reverse=True)
 selected={"openai":by_id.get(TARGETS["openai"]),"google":google[0] if google else None,"mistral":by_id.get(TARGETS["mistral"])};missing=[k for k,v in selected.items() if v is None];out=[]
 for provider,m in selected.items():
  if m is None:continue
  profile=VOICE_PROFILES[provider];validate_voices(profile,[profile["host"],profile["analyst"]]);arch=m["architecture"];top=m.get("top_provider") or {};out.append(Candidate(provider,m["id"],{"host":profile["host"],"analyst":profile["analyst"]},dict(m.get("pricing") or {}),tuple(arch.get("output_modalities",[])),tuple(m.get("supported_parameters") or []),top.get("context_length")))
 return out,missing

def validate_voices(profile:dict[str,Any],voices:list[str])->None:
 if len(voices)!=2 or voices[0]==voices[1] or any(v not in profile["voices"] for v in voices):raise CalibrationError("unsupported_or_duplicate_voice")

def build_request(candidate:Candidate,turn:dict[str,Any])->dict[str,Any]:
 speaker=turn.get("speaker");
 if speaker not in ("host","analyst") or not isinstance(turn.get("text"),str) or not turn["text"].strip():raise CalibrationError("turn_invalid")
 profile=VOICE_PROFILES[candidate.provider];body={"model":candidate.model,"input":turn["text"],"voice":candidate.voices[speaker],"response_format":"mp3","speed":1.0}
 if profile["instructions"]:body["instructions"]=DELIVERY
 return body

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

def estimate(candidates:list[Candidate],characters:int)->dict[str,Any]:
 rows=[]
 for c in candidates:
  prompt=float(c.pricing.get("prompt",0));rows.append({"model":c.model,"input_price":c.pricing.get("prompt"),"characters":characters,"input_cost_upper_bound_usd":round(prompt*characters,6),"completion_price":c.pricing.get("completion")})
 return {"candidates":rows,"input_cost_upper_bound_usd":round(sum(x["input_cost_upper_bound_usd"] for x in rows),6)}

def paid_gate(*,authorized:bool,candidates:list[Candidate],estimated_total:float,output:Path)->None:
 if not authorized:raise CalibrationError("explicit_paid_authorization_required")
 if len(candidates)!=3:raise CalibrationError("three_candidates_required")
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
 p=argparse.ArgumentParser();p.add_argument("command",choices=("preflight","generate"));p.add_argument("--dialogue",type=Path,default=Path("calibration/tts/blind-test-v1/dialogue.json"));p.add_argument("--output",type=Path,required=True);p.add_argument("--authorize-paid",action="store_true");a=p.parse_args();key=os.getenv("OPENROUTER_API_KEY");
 if not key:raise CalibrationError("openrouter_key_missing")
 doc=requests.get(MODELS_URL,headers={"Authorization":"Bearer "+key},timeout=30).json();candidates,missing=discover_models(doc);d=dialogue(a.dialogue);chars=sum(len(x["text"]) for x in d["turns"]);cost=estimate(candidates,chars);report={"models":[{"model":x.model,"provider":x.provider,"voices":x.voices,"output_modalities":x.output_modalities,"pricing":x.pricing,"supported_parameters":x.supported_parameters,"context_length":x.context_length,"formats":sorted(VOICE_PROFILES[x.provider]["formats"]),"speed_supported":VOICE_PROFILES[x.provider]["speed"]} for x in candidates],"missing_candidates":missing,"turns":len(d["turns"]),"requests":len(d["turns"])*len(candidates),"characters_per_candidate":chars,"expected_total_input_characters":chars*len(candidates),"estimated_cost":cost,"output":str(a.output),"production_writes":0,"r2_calls":0,"frontend_writes":0,"paid_calls":0,"ready":len(candidates)==3}
 print(json.dumps(report,indent=2,sort_keys=True))
 if a.command=="preflight":return 0 if report["ready"] else 2
 paid_gate(authorized=a.authorize_paid,candidates=candidates,estimated_total=cost["input_cost_upper_bound_usd"],output=a.output);a.output.mkdir(parents=True,exist_ok=False,mode=0o700);mapping=secure_mapping(candidates);records={};public=[];dialogue_hash="sha256:"+hashlib.sha256(a.dialogue.read_bytes()).hexdigest()
 for anonymous,candidate in mapping.items():
  private=a.output/("."+anonymous+"-turns");private.mkdir(mode=0o700);files=[];records[anonymous]=[]
  for turn in d["turns"]:
   body=build_request(candidate,turn);audio,meta=request_turn(requests.post,key,body,max_retries=1);path=private/(turn["turn_id"]+".mp3");path.write_bytes(audio);os.chmod(path,0o600);files.append(path);records[anonymous].append({**meta,"turn_id":turn["turn_id"],"model":candidate.model,"voice":body["voice"]})
  final=a.output/(anonymous+".mp3");assemble(files,[x["pause_after_ms"] for x in d["turns"]],final);info=probe(final);public.append({"candidate_id":anonymous,"file":final.name,**{k:info[k] for k in ("duration_seconds","bytes","sha256")},"dialogue_sha256":dialogue_hash,"generated_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())});shutil.rmtree(private)
 write_reveal(a.output/"tts-reveal.json",mapping,records);manifest={"schema_version":"1.0.0","dialogue_sha256":dialogue_hash,"candidates":public};(a.output/"manifest.public.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n");shutil.copy2(Path("calibration/tts/blind-test-v1/evaluation.md"),a.output/"evaluation.md");print(json.dumps({"generated":len(public),"output":str(a.output),"paid_requests":sum(len(x) for x in records.values())},sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
