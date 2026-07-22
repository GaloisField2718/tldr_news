"""Isolated, human-scored illustration prompt calibration lab."""
from __future__ import annotations
import hashlib,html,json,os,secrets,subprocess,tempfile
from dataclasses import asdict,dataclass
from pathlib import Path
from typing import Sequence
from .artifacts import load_artifact,validate_all
from .candidates import Candidate,load_date
from .config import Config
from .core import EditorialError
from .image import assemble_prompt,decode_image,normalize_raster
from .illustration_concepts import CONCEPT_SCHEMA_VERSION,ConceptProfile,get_concept
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

AMD_ANTI_DEFAULT_CLAUSE="Do not default to a single centered server rack, a server represented as a skyscraper, a heroic product shot, an upward arrow, or a generic futuristic server room unless the selected concept explicitly requires it."

def _digest(value:dict)->str:
 return "sha256:"+hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def _official_concept(context:CalibrationContext)->ConceptProfile:
 refs=tuple((c.issue_id,c.article_id) for c in context.sources);brief=context.brief
 return ConceptProfile("official-visual-brief",brief["central_subject"],brief["visual_metaphor"],brief["composition"],tuple(brief["forbidden_elements"]),"Validated official editorial visual brief.",refs)

def _concept_hash(concept:ConceptProfile)->str:return _digest(asdict(concept))
def _original_brief_hash(context:CalibrationContext)->str:return _digest({"brief":context.brief,"source_references":[[c.issue_id,c.article_id] for c in context.sources]})

def assemble_experimental_prompt(context:CalibrationContext,style:PromptProfile,concept:ConceptProfile)->str:
 refs={(c.issue_id,c.article_id) for c in context.sources}
 if concept.required_source_references and not set(concept.required_source_references).issubset(refs):raise EditorialError("calibration_concept_source_requirement_missing")
 lines=[style.preamble,"","Experimental editorial concept:",f"Factual rationale: {concept.factual_rationale}",f"Central subject: {concept.central_subject_override}",f"Visual metaphor: {concept.visual_metaphor_override}",f"Composition: {concept.composition_override}","Concept-specific forbidden elements: "+(", ".join(concept.forbidden_elements) or "none"),"",AMD_ANTI_DEFAULT_CLAUSE,"","Source stories (use only these exact facts):"]
 for source in context.sources:lines.extend((f"Title: {source.title}",f"Summary: {source.summary}"))
 return "\n".join(lines).strip()+"\n"

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

def read_blind_mapping(path:Path)->dict:
 """Read current or round-1 private maps without mutating either format."""
 try:mapping=json.loads(path.read_text(encoding="utf-8"))["mapping"]
 except (OSError,json.JSONDecodeError,KeyError,TypeError) as exc:raise EditorialError("calibration_blind_map_invalid") from exc
 normalized={}
 for candidate,value in mapping.items():
  if not isinstance(value,dict):raise EditorialError("calibration_blind_map_invalid")
  if "style_profile_id" in value:normalized[candidate]=dict(value)
  elif "profile_id" in value:normalized[candidate]={"style_profile_id":value["profile_id"],"concept_profile_id":"official-visual-brief","sample_index":value.get("sample_index",1)}
  else:raise EditorialError("calibration_blind_map_invalid")
 return normalized

def _gallery(candidates:list[dict],context:CalibrationContext)->str:
 source="".join(f"<p><strong>{html.escape(c.title)}</strong><br>{html.escape(c.summary)}</p>" for c in context.sources);cards=[]
 for c in candidates:
  media=f'<button class="image-button" type="button" aria-label="Enlarge {html.escape(c["candidate_id"])}"><img src="{html.escape(c["image_file"])}" alt="Anonymous calibration candidate"></button>' if c.get("image_file") else '<div class="placeholder">No image generated</div>'
  cards.append(f'<article>{media}<h2>{html.escape(c["candidate_id"])}</h2></article>')
 return """<!doctype html><meta charset="utf-8"><title>Blind illustration calibration</title>
<style>body{font:16px system-ui;margin:2rem auto;max-width:1800px;background:#eee;color:#111;padding:0 1rem}.source{max-width:900px;background:white;padding:1rem;margin-bottom:2rem}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1.5rem}article{background:white;padding:1rem}.image-button{display:block;width:100%;padding:0;border:0;background:none;cursor:zoom-in}img,.placeholder{display:block;width:100%;aspect-ratio:3/2;object-fit:cover;background:#ddd}.placeholder{display:grid;place-items:center}h2{font-size:1rem;margin:.75rem 0 0}dialog{border:0;padding:0;background:#111;max-width:95vw}dialog img{width:auto;max-width:95vw;max-height:92vh;aspect-ratio:auto;object-fit:contain}@media(max-width:800px){.grid{grid-template-columns:1fr}}</style>
<h1>Blind illustration calibration</h1><section class="source"><h2>Source facts</h2>"""+source+"""</section><div class="grid">"""+"".join(cards)+"""</div><dialog id="zoom"><img alt="Enlarged anonymous candidate"></dialog><script>const d=document.querySelector('#zoom'),z=d.querySelector('img');document.querySelectorAll('.image-button img').forEach(i=>i.parentElement.addEventListener('click',()=>{z.src=i.src;d.showModal()}));d.addEventListener('click',()=>d.close());</script>\n"""

def _write_outputs(output:Path,context:CalibrationContext,candidates:list[dict],mapping:dict)->None:
 order=list(candidates);secrets.SystemRandom().shuffle(order)
 manifest={"schema_version":CALIBRATION_SCHEMA_VERSION,"profile_schema_version":PROFILE_SCHEMA_VERSION,"concept_schema_version":CONCEPT_SCHEMA_VERSION,"date":context.date,"model":next((x["model"] for x in candidates),None),"source_context":[{"issue_id":c.issue_id,"article_id":c.article_id,"title":c.title,"summary":c.summary} for c in context.sources],"candidates":order}
 blind={"schema_version":CALIBRATION_SCHEMA_VERSION,"mapping":mapping}
 score={"schema_version":CALIBRATION_SCHEMA_VERSION,"rubric":RUBRIC,"scores":[{"candidate_id":x["candidate_id"],"hard_rejection":False,"hard_rejection_reasons":[],"ratings":{c["id"]:None for c in RUBRIC["weighted_criteria"]},"first_impression":"","strongest_quality":"","strongest_weakness":"","feels_human_directed":None,"advance_to_round_two":None} for x in order]}
 _json(output/"manifest.json",manifest);_json(output/"blind-map.json",blind);_json(output/"score-template.json",score)
 _atomic_bytes(output/"gallery.html",_gallery(order,context).encode(),0o600)

def parse_combinations(value:str)->list[tuple[str,str]]:
 if not value.strip():raise EditorialError("calibration_combinations_required")
 pairs=[]
 for entry in value.split(","):
  parts=[x.strip() for x in entry.split(":")]
  if len(parts)!=2 or not all(parts):raise EditorialError("calibration_combination_malformed")
  pairs.append((parts[0],parts[1]))
 return pairs

def run_calibration(*,context:CalibrationContext,profiles:Sequence[PromptProfile],output:Path,cfg:Config,live:bool,client=None,concepts:Sequence[ConceptProfile]|None=None,combinations:Sequence[tuple[PromptProfile,ConceptProfile]]|None=None,samples_per_combination:int=1,samples_per_profile:int|None=None)->dict:
 legacy=concepts is None and combinations is None
 if samples_per_profile is not None:
  if not legacy or samples_per_combination!=1:raise EditorialError("calibration_sample_flags_conflict")
  if not 1<=samples_per_profile<=5:raise EditorialError("calibration_samples_per_profile_invalid")
  samples_per_combination=samples_per_profile
 elif not 1<=samples_per_combination<=3:raise EditorialError("calibration_samples_per_combination_invalid")
 if combinations is not None:pairs=list(combinations)
 else:
  selected_concepts=list(concepts) if concepts is not None else [_official_concept(context)]
  pairs=[(style,concept) for style in profiles for concept in selected_concepts]
 assignments=[(style,concept,sample_index) for style,concept in pairs for sample_index in range(1,samples_per_combination+1)];ids=[]
 for _ in assignments:
  while True:
   value="candidate-"+secrets.token_hex(4)
   if value not in ids:ids.append(value);break
 mapping={candidate:{"style_profile_id":style.profile_id,"concept_profile_id":concept.concept_id,"sample_index":sample_index} for candidate,(style,concept,sample_index) in zip(ids,assignments)};records=[];failed=False;network_calls=0;image_client=(client or OpenRouterClient(cfg)) if live else None;original_hash=_original_brief_hash(context)
 for candidate_id,(style,concept,sample_index) in zip(ids,assignments):
  prompt=assemble_prompt(context.brief,list(context.sources),style) if legacy else assemble_experimental_prompt(context,style,concept);prompt_sha="sha256:"+hashlib.sha256(prompt.encode()).hexdigest()
  record={"candidate_id":candidate_id,"status":"planned" if not live else "not_attempted","image_file":None,"sha256":None,"width":None,"height":None,"bytes":None,"prompt_sha256":prompt_sha,"original_visual_brief_sha256":original_hash,"experimental_concept_sha256":_concept_hash(concept),"model":cfg.image_model,"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0,"cost_usd":0.0},"source_references":[{"issue_id":c.issue_id,"article_id":c.article_id} for c in context.sources]}
  records.append(record)
  if not live or failed:continue
  try:
   network_calls+=1;result=image_client.image(prompt)
   raw,media=decode_image(result.value,result.media_type);fd,tmp=tempfile.mkstemp(prefix="tldr-calibration-provider-",suffix=".raster")
   try:
    os.fchmod(fd,0o600)
    with os.fdopen(fd,"wb") as handle:handle.write(raw);handle.flush();os.fsync(handle.fileno())
    image=normalize_raster(Path(tmp),media,cfg.max_provider_image_bytes,cfg.max_image_pixels,cfg.max_image_bytes)
   finally:
    try:os.unlink(tmp)
    except FileNotFoundError:pass
   filename=candidate_id+".webp";_atomic_bytes(output/filename,image.data);record.update(status="ready",image_file=filename,sha256=image.sha256,width=image.width,height=image.height,bytes=image.bytes,usage=result.usage)
  except EditorialError as exc:record.update(status="failed",failure_category=str(exc));failed=True
 _write_outputs(output,context,records,mapping)
 return {"date":context.date,"candidate_count":len(records),"ready_count":sum(x["status"]=="ready" for x in records),"failed_count":sum(x["status"]=="failed" for x in records),"network_calls":network_calls,"editorial_calls":0,"r2_calls":0,"live":live,"success":not failed,"output_dir":str(output)}

def calibrate_images(*,date:str,profile_ids:Sequence[str]|None=None,output_dir:Path,max_images:int,concept_ids:Sequence[str]|None=None,combinations:Sequence[tuple[str,str]]|None=None,samples_per_combination:int=1,samples_per_profile:int|None=None,require_live:bool=False,acknowledge_cost:bool=False,generated:Path=Path("generated"),editorial_output:Path=Path("generated/editorial"),config:Config|None=None,client=None,context:CalibrationContext|None=None)->dict:
 if not date:raise EditorialError("calibration_date_required")
 explicit=combinations is not None
 if explicit and (profile_ids is not None or concept_ids is not None):raise EditorialError("calibration_combination_mode_conflict")
 profiles=[];concepts=None;resolved_combinations=None
 if explicit:
  if not combinations:raise EditorialError("calibration_combinations_required")
  normalized=[]
  for pair in combinations:
   if not isinstance(pair,(tuple,list)) or len(pair)!=2 or not all(isinstance(x,str) and x.strip() for x in pair):raise EditorialError("calibration_combination_malformed")
   normalized.append((pair[0].strip(),pair[1].strip()))
  if len(set(normalized))!=len(normalized):raise EditorialError("calibration_duplicate_combination")
  resolved_combinations=[]
  for style_id,concept_id in normalized:
   try:style=get_profile(style_id)
   except KeyError as exc:raise EditorialError("calibration_combination_style_unknown") from exc
   try:concept=get_concept(concept_id)
   except KeyError as exc:raise EditorialError("calibration_combination_concept_unknown") from exc
   resolved_combinations.append((style,concept))
 else:
  if not profile_ids:raise EditorialError("calibration_profiles_required")
  if len(set(profile_ids))!=len(profile_ids):raise EditorialError("calibration_duplicate_profile")
  try:profiles=[get_profile(x) for x in profile_ids]
  except KeyError as exc:raise EditorialError("calibration_profile_unknown") from exc
  if concept_ids is not None:
   if not concept_ids:raise EditorialError("calibration_concepts_required")
   if len(set(concept_ids))!=len(concept_ids):raise EditorialError("calibration_duplicate_concept")
   try:concepts=[get_concept(x) for x in concept_ids]
   except KeyError as exc:raise EditorialError("calibration_concept_unknown") from exc
 if samples_per_profile is not None:
  if explicit or concepts is not None or samples_per_combination!=1:raise EditorialError("calibration_sample_flags_conflict")
  if not 1<=samples_per_profile<=5:raise EditorialError("calibration_samples_per_profile_invalid")
  samples=samples_per_profile
 else:
  if not 1<=samples_per_combination<=3:raise EditorialError("calibration_samples_per_combination_invalid")
  samples=samples_per_combination
 pair_count=len(resolved_combinations) if explicit else len(profiles)*(len(concepts) if concepts is not None else 1)
 total=pair_count*samples
 if max_images<1 or total>max_images:raise EditorialError("calibration_image_limit")
 if require_live!=acknowledge_cost:raise EditorialError("calibration_live_flags_required")
 live=require_live and acknowledge_cost
 if live and os.getenv("CI"):raise EditorialError("calibration_live_forbidden_in_ci")
 _require_clean();root=_git_root();output=_prepare_output(output_dir,root);cfg=config or Config.from_env()
 if live:cfg.require_openrouter()
 context=context or _context(date,generated,editorial_output,cfg)
 if context.date!=date:raise EditorialError("calibration_context_date_mismatch")
 return run_calibration(context=context,profiles=profiles,concepts=concepts,combinations=resolved_combinations,output=output,cfg=cfg,live=live,client=client,samples_per_combination=samples if samples_per_profile is None else 1,samples_per_profile=samples_per_profile)
