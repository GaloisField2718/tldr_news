"""Isolated, human-scored illustration prompt calibration lab."""
from __future__ import annotations
import hashlib,html,json,os,secrets,subprocess,tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from .artifacts import load_artifact,validate_all
from .candidates import Candidate,load_date
from .config import Config
from .core import EditorialError
from .image import assemble_prompt,decode_image,normalize_raster
from .illustration_prompts import PROFILE_SCHEMA_VERSION,PromptProfile,get_profile
from .openrouter import OpenRouterClient

CALIBRATION_SCHEMA_VERSION="1.0.0"
RUBRIC={
 "scale":{"minimum":1,"maximum":5},
 "weighted_criteria":[
  {"id":"absence_of_ai_cliches","weight":0.30,"label":"Absence of obvious AI visual clichés"},
  {"id":"editorial_authorship","weight":0.20,"label":"Sense of intentional editorial authorship"},
  {"id":"factual_grounding","weight":0.15,"label":"Factual grounding and absence of invented detail"},
  {"id":"composition","weight":0.15,"label":"Composition and immediate readability"},
  {"id":"newspaper_fit","weight":0.10,"label":"Fit with the TLDR Index newspaper design"},
  {"id":"small_size_readability","weight":0.10,"label":"Readability at column/social-card size"},
 ],
 "hard_rejections":["visible text or malformed lettering","logos or trademarks","invented factual evidence","generic neon/circuit-board/futuristic imagery","obvious stock 3D render aesthetics","incoherent object geometry","unusable crop","severe visual artifacts"],
 "notes":["first_impression","strongest_quality","strongest_weakness","feels_human_directed","advance_to_round_two"],
}

@dataclass(frozen=True)
class CalibrationContext:
 date:str
 brief:dict
 sources:tuple[Candidate,...]

def _git_root()->Path:
 try:raw=subprocess.run(["git","rev-parse","--show-toplevel"],check=True,capture_output=True,timeout=10).stdout
 except (OSError,subprocess.SubprocessError) as exc:raise EditorialError("calibration_git_root_failed") from exc
 return Path(os.fsdecode(raw.rstrip(b"\n"))).resolve()

def _require_clean()->None:
 try:raw=subprocess.run(["git","status","--porcelain=v1","-z","--untracked-files=all"],check=True,capture_output=True,timeout=10).stdout
 except (OSError,subprocess.SubprocessError) as exc:raise EditorialError("calibration_git_status_failed") from exc
 if raw:raise EditorialError("calibration_git_workspace_not_clean")

def _prepare_output(output:Path,root:Path)->Path:
 if not output.is_absolute():raise EditorialError("calibration_output_must_be_absolute")
 if output.is_symlink():raise EditorialError("calibration_output_symlink")
 try:parent=output.parent.resolve(strict=True)
 except OSError as exc:raise EditorialError("calibration_output_parent_invalid") from exc
 candidate=parent/output.name
 try:candidate.relative_to(root)
 except ValueError:pass
 else:raise EditorialError("calibration_output_inside_git")
 if candidate.exists():
  if candidate.is_symlink() or not candidate.is_dir():raise EditorialError("calibration_output_invalid")
  if any(candidate.iterdir()):raise EditorialError("calibration_output_not_empty")
 else:candidate.mkdir(mode=0o700)
 os.chmod(candidate,0o700)
 return candidate

def _context(date:str,generated:Path,editorial_output:Path,cfg:Config)->CalibrationContext:
 errors=validate_all(editorial_output,generated,None,cfg.r2_public_base_url,cfg.max_candidates,cfg.editorial_model,cfg.image_model,cfg.max_provider_image_bytes,cfg.max_image_pixels,cfg.max_image_bytes)
 if errors:raise EditorialError("calibration_official_artifact_invalid")
 artifact=load_artifact(editorial_output,date)
 if not artifact:raise EditorialError("calibration_artifact_missing")
 brief=artifact.get("plan",{}).get("visual_brief",{})
 if brief.get("mode")=="none":raise EditorialError("calibration_visual_brief_missing")
 by={(c.issue_id,c.article_id):c for c in load_date(generated,date)}
 try:sources=tuple(by[(x["issue_id"],x["article_id"])] for x in brief["sources"])
 except (KeyError,TypeError) as exc:raise EditorialError("calibration_source_reference_invalid") from exc
 if not sources:raise EditorialError("calibration_source_reference_invalid")
 prompt_brief={k:brief[k] for k in ("mode","central_subject","visual_metaphor","composition","forbidden_elements","alt_text")}
 return CalibrationContext(date,prompt_brief,sources)

def _atomic_bytes(path:Path,data:bytes,mode:int=0o600)->None:
 fd,tmp=tempfile.mkstemp(prefix=".calibration-",dir=path.parent)
 try:
  os.fchmod(fd,mode)
  with os.fdopen(fd,"wb") as handle:handle.write(data);handle.flush();os.fsync(handle.fileno())
  os.replace(tmp,path)
 finally:
  try:os.unlink(tmp)
  except FileNotFoundError:pass

def _json(path:Path,value:dict,mode:int=0o600)->None:_atomic_bytes(path,(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode(),mode)

def _gallery(candidates:list[dict],context:CalibrationContext)->str:
 source="".join(f"<p><strong>{html.escape(c.title)}</strong><br>{html.escape(c.summary)}</p>" for c in context.sources)
 cards=[]
 for c in candidates:
  media=f'<img src="{html.escape(c["image_file"])}" alt="Anonymous calibration candidate">' if c.get("image_file") else '<div class="placeholder">No image generated</div>'
  cards.append(f'<article><h2>{html.escape(c["candidate_id"])}</h2>{media}<div class="source">{source}</div></article>')
 return """<!doctype html><meta charset="utf-8"><title>Blind illustration calibration</title>
<style>body{font:16px system-ui;margin:2rem;background:#eee;color:#111}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:2rem}article{background:white;padding:1rem}img,.placeholder{display:block;width:100%;aspect-ratio:3/2;object-fit:cover;background:#ddd}.placeholder{display:grid;place-items:center}.source{font-size:.9rem}h2{font-size:1rem}</style>
<h1>Blind illustration calibration</h1><div class="grid">"""+"".join(cards)+"</div>\n"

def _write_outputs(output:Path,context:CalibrationContext,candidates:list[dict],mapping:dict)->None:
 order=list(candidates);secrets.SystemRandom().shuffle(order)
 manifest={"schema_version":CALIBRATION_SCHEMA_VERSION,"profile_schema_version":PROFILE_SCHEMA_VERSION,"date":context.date,"model":next((x["model"] for x in candidates),None),"source_context":[{"issue_id":c.issue_id,"article_id":c.article_id,"title":c.title,"summary":c.summary} for c in context.sources],"candidates":order}
 blind={"schema_version":CALIBRATION_SCHEMA_VERSION,"mapping":mapping}
 score={"schema_version":CALIBRATION_SCHEMA_VERSION,"rubric":RUBRIC,"scores":[{"candidate_id":x["candidate_id"],"hard_rejection":False,"hard_rejection_reasons":[],"ratings":{c["id"]:None for c in RUBRIC["weighted_criteria"]},"first_impression":"","strongest_quality":"","strongest_weakness":"","feels_human_directed":None,"advance_to_round_two":None} for x in order]}
 _json(output/"manifest.json",manifest);_json(output/"blind-map.json",blind);_json(output/"score-template.json",score)
 _atomic_bytes(output/"gallery.html",_gallery(order,context).encode(),0o600)

def run_calibration(*,context:CalibrationContext,profiles:Sequence[PromptProfile],output:Path,cfg:Config,live:bool,client=None,samples_per_profile:int=1)->dict:
 if not 1<=samples_per_profile<=5:raise EditorialError("calibration_samples_per_profile_invalid")
 assignments=[(profile,sample_index) for profile in profiles for sample_index in range(1,samples_per_profile+1)];ids=[]
 for _ in assignments:
  while True:
   value="candidate-"+secrets.token_hex(4)
   if value not in ids:ids.append(value);break
 mapping={candidate:{"profile_id":profile.profile_id,"sample_index":sample_index} for candidate,(profile,sample_index) in zip(ids,assignments)};records=[];failed=False;network_calls=0;image_client=(client or OpenRouterClient(cfg)) if live else None
 for candidate_id,(profile,sample_index) in zip(ids,assignments):
  prompt=assemble_prompt(context.brief,list(context.sources),profile);prompt_sha="sha256:"+hashlib.sha256(prompt.encode()).hexdigest()
  record={"candidate_id":candidate_id,"status":"planned" if not live else "not_attempted","image_file":None,"sha256":None,"width":None,"height":None,"bytes":None,"prompt_sha256":prompt_sha,"model":cfg.image_model,"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0,"cost_usd":0.0},"source_references":[{"issue_id":c.issue_id,"article_id":c.article_id} for c in context.sources]}
  records.append(record)
  if not live or failed:continue
  try:
   network_calls+=1;result=image_client.image(prompt)
   raw,media=decode_image(result.value,result.media_type)
   fd,tmp=tempfile.mkstemp(prefix="tldr-calibration-provider-",suffix=".raster")
   try:
    os.fchmod(fd,0o600)
    with os.fdopen(fd,"wb") as handle:handle.write(raw);handle.flush();os.fsync(handle.fileno())
    image=normalize_raster(Path(tmp),media,cfg.max_provider_image_bytes,cfg.max_image_pixels,cfg.max_image_bytes)
   finally:
    try:os.unlink(tmp)
    except FileNotFoundError:pass
   filename=candidate_id+".webp";_atomic_bytes(output/filename,image.data)
   record.update(status="ready",image_file=filename,sha256=image.sha256,width=image.width,height=image.height,bytes=image.bytes,usage=result.usage)
  except EditorialError as exc:
   record.update(status="failed",failure_category=str(exc));failed=True
 _write_outputs(output,context,records,mapping)
 return {"date":context.date,"candidate_count":len(records),"ready_count":sum(x["status"]=="ready" for x in records),"failed_count":sum(x["status"]=="failed" for x in records),"network_calls":network_calls,"editorial_calls":0,"r2_calls":0,"live":live,"success":not failed,"output_dir":str(output)}

def calibrate_images(*,date:str,profile_ids:Sequence[str],output_dir:Path,max_images:int,samples_per_profile:int=1,require_live:bool=False,acknowledge_cost:bool=False,generated:Path=Path("generated"),editorial_output:Path=Path("generated/editorial"),config:Config|None=None,client=None,context:CalibrationContext|None=None)->dict:
 if not date:raise EditorialError("calibration_date_required")
 if not profile_ids:raise EditorialError("calibration_profiles_required")
 if not 1<=samples_per_profile<=5:raise EditorialError("calibration_samples_per_profile_invalid")
 total=len(profile_ids)*samples_per_profile
 if max_images<1 or total>max_images:raise EditorialError("calibration_image_limit")
 if len(set(profile_ids))!=len(profile_ids):raise EditorialError("calibration_duplicate_profile")
 try:profiles=[get_profile(x) for x in profile_ids]
 except KeyError as exc:raise EditorialError("calibration_profile_unknown") from exc
 if require_live!=acknowledge_cost:raise EditorialError("calibration_live_flags_required")
 live=require_live and acknowledge_cost
 if live and os.getenv("CI"):raise EditorialError("calibration_live_forbidden_in_ci")
 _require_clean();root=_git_root();output=_prepare_output(output_dir,root);cfg=config or Config.from_env()
 if live:cfg.require_openrouter()
 context=context or _context(date,generated,editorial_output,cfg)
 if context.date!=date:raise EditorialError("calibration_context_date_mismatch")
 return run_calibration(context=context,profiles=profiles,output=output,cfg=cfg,live=live,client=client,samples_per_profile=samples_per_profile)
