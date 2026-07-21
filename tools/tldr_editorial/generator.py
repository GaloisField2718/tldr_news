"""End-to-end optional Daily editorial and illustration publication stage."""
from __future__ import annotations
import copy,json,os,subprocess,tempfile
from datetime import datetime,timezone
from pathlib import Path
from .artifacts import load_artifact,write_artifact
from .candidates import dossier,latest_date,load_date,shortlist,dossier_size
from .config import Config
from .core import (EDITORIAL_PROMPT_VERSION,EDITORIAL_SCHEMA_VERSION,GENERATOR_VERSION,
    ILLUSTRATION_PROMPT_VERSION,SCHEMA_VERSION,EditorialError,hash_parts,image_configuration,object_key,sha256_bytes)
from .image import assemble_prompt,decode_image,normalize_raster
from .openrouter import OpenRouterClient
from .plan import fallback,resolve_plan,validate_plan
from .r2_storage import R2Storage,build_public_url

ZERO={"prompt_tokens":0,"completion_tokens":0,"total_tokens":0,"cost_usd":0.0}
def _illustration(status,code=None):
    x={"status":status,"provider":None,"object_key":None,"public_url":None,"media_type":None,"width":None,"height":None,"bytes":None,"sha256":None,"aspect_ratio":"3:2","resolution":"1K","attribution":"AI-generated editorial illustration","storage_verified":False}
    if code: x["failure_code"]=code
    return x

def _now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

def _require_clean_live_workspace(output: Path) -> None:
    if output.is_symlink() or any(p.name.startswith(".tldr-editorial-") or p.suffix==".tmp" for p in output.rglob("*") if output.exists()):
        raise EditorialError("live_output_not_clean")
    try: result=subprocess.run(["git","status","--porcelain"],capture_output=True,text=True,check=True,timeout=10)
    except (OSError,subprocess.SubprocessError) as exc: raise EditorialError("live_git_status_failed") from exc
    if result.stdout.strip(): raise EditorialError("live_git_workspace_not_clean")

def _existing_illustration_hash(existing:dict,candidates:list,config:Config)->str|None:
    stored=existing.get("illustration_input_hash")
    if stored is None:return None
    by_ref={(c.issue_id,c.article_id):c for c in candidates};vb=existing["plan"]["visual_brief"]
    sources=[by_ref[(x["issue_id"],x["article_id"])] for x in vb["sources"]]
    brief={"mode":vb["mode"],"source_candidate_ids":[c.candidate_id for c in sources],**{k:vb[k] for k in ("central_subject","visual_metaphor","composition","forbidden_elements","alt_text")}}
    cfg=image_configuration(config.max_provider_image_bytes,config.max_image_pixels,config.max_image_bytes)
    return hash_parts(brief,[{"title":c.title,"summary":c.summary} for c in sources],config.image_model,ILLUSTRATION_PROMPT_VERSION,cfg)

def generate(*,generated=Path("generated"),output=Path("generated/editorial"),date=None,latest=False,offline=False,dry_run=False,require_live=False,force=False,retry_image=False,config=None,client=None,storage=None)->dict:
    config=config or Config.from_env(); date=date or latest_date(generated)
    if require_live and (offline or dry_run or not config.enabled): raise EditorialError("live_generation_not_enabled")
    if require_live:
        if os.getenv("CI"): raise EditorialError("live_generation_forbidden_in_ci")
        config.require_openrouter(); config.require_r2(); _require_clean_live_workspace(output)
    candidates=shortlist(load_date(generated,date),config.max_candidates); dos=dossier(candidates)
    editorial_hash=hash_parts(dos,config.editorial_model,EDITORIAL_PROMPT_VERSION,EDITORIAL_SCHEMA_VERSION)
    existing=load_artifact(output,date)
    # Clean no-op, including persisted failures (prevents every-minute retries).
    illustration_stale=False
    if existing and existing.get("editorial_input_hash")==editorial_hash and existing.get("illustration_input_hash"):
        try: illustration_stale=_existing_illustration_hash(existing,candidates,config)!=existing.get("illustration_input_hash")
        except (KeyError,TypeError): illustration_stale=True
    if existing and existing.get("editorial_input_hash")==editorial_hash and not force:
        retryable=retry_image and existing.get("status")=="editorial_only" and existing.get("illustration_input_hash")
        should_live=config.enabled and not offline and not dry_run
        disabled_upgrade=should_live and existing.get("status")=="disabled"
        if not retryable and not disabled_upgrade and not illustration_stale:
            if existing.get("illustration",{}).get("status")=="ready" and config.r2_public_base_url:
                copy_a=copy.deepcopy(existing); key=copy_a["illustration"]["object_key"]
                new=storage.build_public_url(key) if storage else build_public_url(config,key)
                if new!=copy_a["illustration"]["public_url"]:
                    copy_a["illustration"]["public_url"]=new
                    if not dry_run: write_artifact(output,date,copy_a)
                    return {"date":date,"status":copy_a["status"],"written":not dry_run,"network_calls":0,"r2_calls":0,"dossier_bytes":dossier_size(candidates),"public_url_updated":True}
            return {"date":date,"status":existing["status"],"written":False,"network_calls":0,"r2_calls":0,"dossier_bytes":dossier_size(candidates),"noop":True}
    live=config.enabled and not offline and not dry_run
    plan=fallback(candidates); status="disabled" if not config.enabled else "deterministic_fallback"
    failure=None; editorial_usage=dict(ZERO); image_usage=dict(ZERO); erid=irid=None; calls=0; r2calls=0
    valid_ai=False
    reuse_existing_plan=live and (retry_image or illustration_stale) and existing and existing.get("editorial_input_hash")==editorial_hash
    if live and not reuse_existing_plan:
        if not config.api_key:
            if require_live: config.require_openrouter()
            failure="openrouter_key_missing"
        else:
            try:
                client=client or OpenRouterClient(config); result=client.editorial(dos); calls+=1
                plan=validate_plan(result.value,candidates); editorial_usage=result.usage; erid=result.request_id; valid_ai=True; status="editorial_only"
            except EditorialError as exc: failure=str(exc)
    elif reuse_existing_plan:
        # Existing source-resolved plan cannot safely be converted back to candidate IDs;
        # resolve references deterministically against the current dossier.
        refs={(c.issue_id,c.article_id):c.candidate_id for c in candidates}
        ep=existing.get("plan",{}); vb=ep.get("visual_brief",{})
        try:
            lead=refs[(ep["lead"]["issue_id"],ep["lead"]["article_id"])]
            plan={"lead_candidate_id":lead,"front_page":[{"candidate_id":refs[(x["issue_id"],x["article_id"])],"role":x["role"]} for x in ep["front_page"]],"section_order":ep["section_order"],
                  "visual_brief":{"mode":vb["mode"],"source_candidate_ids":[refs[(x["issue_id"],x["article_id"])] for x in vb["sources"]],**{k:vb[k] for k in ("central_subject","visual_metaphor","composition","forbidden_elements","alt_text")}}}
            plan=validate_plan(plan,candidates); valid_ai=plan["visual_brief"]["mode"]!="none"; status="editorial_only"; editorial_usage=existing["usage"]["editorial"]
        except Exception as exc: raise EditorialError("retry_image_stale_plan") from exc
    resolved=resolve_plan(plan,candidates)
    illustration_hash=None; final_prompt=None; ill=_illustration("disabled" if not config.enabled else "not_requested")
    if valid_ai and plan["visual_brief"]["mode"]!="none":
        by={c.candidate_id:c for c in candidates}; sources=[by[x] for x in plan["visual_brief"]["source_candidate_ids"]]
        final_prompt=assemble_prompt(plan["visual_brief"],sources)
        image_cfg=image_configuration(config.max_provider_image_bytes,config.max_image_pixels,config.max_image_bytes)
        illustration_hash=hash_parts(plan["visual_brief"],[{"title":c.title,"summary":c.summary} for c in sources],config.image_model,ILLUSTRATION_PROMPT_VERSION,image_cfg)
        try:
            client=client or OpenRouterClient(config); result=client.image(final_prompt); calls+=1; image_usage=result.usage; irid=result.request_id
        except EditorialError as exc:
            ill=_illustration("generation_failed",str(exc)); failure=str(exc)
        else:
            try: raw,media=decode_image(result.value,result.media_type)
            except EditorialError as exc: ill=_illustration("validation_failed",str(exc)); failure=str(exc)
            else:
                image=None
                source_fd,source_tmp=tempfile.mkstemp(prefix="tldr-provider-",suffix=".raster")
                try:
                    os.fchmod(source_fd,0o600)
                    with os.fdopen(source_fd,"wb") as fh: fh.write(raw); fh.flush(); os.fsync(fh.fileno())
                    try: image=normalize_raster(Path(source_tmp),media,config.max_provider_image_bytes,config.max_image_pixels,config.max_image_bytes)
                    except EditorialError as exc: ill=_illustration("validation_failed",str(exc)); failure=str(exc)
                finally:
                    try: os.unlink(source_tmp)
                    except FileNotFoundError: pass
                if image is not None:
                    final_fd,final_tmp=tempfile.mkstemp(prefix="tldr-final-",suffix=".webp")
                    try:
                        os.fchmod(final_fd,0o600)
                        with os.fdopen(final_fd,"wb") as fh: fh.write(image.data); fh.flush(); os.fsync(fh.fileno())
                        try:
                            key=object_key(date,image.sha256); storage=storage or R2Storage(config); r2calls+=1
                            storage.ensure_uploaded(Path(final_tmp),key,size=image.bytes,sha256=image.sha256,width=image.width,height=image.height,date=date)
                            url=storage.build_public_url(key)
                            ill={"status":"ready","provider":"cloudflare_r2","object_key":key,"public_url":url,"media_type":"image/webp","width":image.width,"height":image.height,"bytes":image.bytes,"sha256":image.sha256,"aspect_ratio":"3:2","resolution":"1K","attribution":"AI-generated editorial illustration","storage_verified":True}
                            status="ai_complete"
                        except EditorialError as exc:
                            code=str(exc); kind="storage_verification_failed" if "verification" in code else "upload_failed"
                            ill=_illustration(kind,code); failure=code
                    finally:
                        try: os.unlink(final_tmp)
                        except FileNotFoundError: pass
    if failure and not valid_ai: status="deterministic_fallback"
    if not config.enabled: status="disabled"
    total=float(editorial_usage.get("cost_usd",0))+float(image_usage.get("cost_usd",0))
    artifact={"schema_version":SCHEMA_VERSION,"generator_version":GENERATOR_VERSION,"date":date,"status":status,"editorial_input_hash":editorial_hash,"illustration_input_hash":illustration_hash,"generated_at":_now(),
      "prompt_versions":{"editorial":EDITORIAL_PROMPT_VERSION,"illustration":ILLUSTRATION_PROMPT_VERSION},"models":{"editorial":config.editorial_model,"illustration":config.image_model},"plan":resolved,"illustration":ill,
      "usage":{"editorial":editorial_usage,"illustration":image_usage,"total_cost_usd":total},
      "generation":{"attempt_count":1 if live else 0,"editorial_request_id":erid,"illustration_request_id":irid,"final_prompt_sha256":sha256_bytes(final_prompt.encode()) if final_prompt else None,"final_prompt":final_prompt,"failure_code":failure}}
    written=False
    if not dry_run: written=any(write_artifact(output,date,artifact))
    return {"date":date,"status":status,"illustration_status":ill["status"],"written":written,"network_calls":calls,"r2_calls":r2calls,"dossier_bytes":dossier_size(candidates),"editorial_input_hash":editorial_hash,"illustration_input_hash":illustration_hash,"dry_run":dry_run}
