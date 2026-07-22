"""Editorial artifact/manifest persistence and offline consistency validation."""
from __future__ import annotations
import json,math,re
from pathlib import Path
from urllib.parse import urlsplit
from .candidates import dossier,load_date,shortlist
from .core import (EDITORIAL_PROMPT_VERSION,EDITORIAL_SCHEMA_VERSION,ILLUSTRATION_PROMPT_VERSION,
                   EditorialError,GENERATOR_VERSION,SCHEMA_VERSION,SHA_RE,atomic_json,canonical_bytes,
                   contained_path,hash_parts,image_configuration,sha256_bytes,validate_object_key)
from .illustration_hash import illustration_input_hash
from .illustration_prompts import get_profile

MANIFEST={"schema_version":SCHEMA_VERSION,"generator_version":GENERATOR_VERSION,"dates":[]}

def artifact_relative(date:str)->str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",date): raise EditorialError("invalid_date")
    return f"{date[:4]}/{date}.json"

def load_artifact(output:Path,date:str):
    path=contained_path(output,artifact_relative(date))
    if not path.exists(): return None
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise EditorialError("artifact_invalid_json") from exc

def manifest_entry(date:str,artifact:dict)->dict:
    raw=canonical_bytes(artifact); ill=artifact["illustration"]
    return {"date":date,"file":artifact_relative(date),"status":artifact["status"],"editorial_input_hash":artifact["editorial_input_hash"],
            "illustration_input_hash":artifact.get("illustration_input_hash"),"sha256":sha256_bytes(raw),"bytes":len(raw),
            "illustration_status":ill["status"],"illustration_object_key":ill.get("object_key"),"illustration_public_url":ill.get("public_url"),
            "illustration_sha256":ill.get("sha256"),"illustration_bytes":ill.get("bytes")}

def write_artifact(output:Path,date:str,artifact:dict)->tuple[bool,bool]:
    if output.is_symlink(): raise EditorialError("symlink_escape")
    output.mkdir(parents=True,exist_ok=True)
    path=contained_path(output,artifact_relative(date)); changed=atomic_json(path,artifact)
    mpath=output/"manifest.json"
    if mpath.exists():
        try: manifest=json.loads(mpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc: raise EditorialError("editorial_manifest_invalid") from exc
    else: manifest=dict(MANIFEST)
    entries=[x for x in manifest.get("dates",[]) if x.get("date")!=date]; entries.append(manifest_entry(date,artifact)); entries.sort(key=lambda x:x["date"])
    manifest={"schema_version":SCHEMA_VERSION,"generator_version":GENERATOR_VERSION,"dates":entries}
    return changed,atomic_json(mpath,manifest)

def _costs(value,path,errors):
    if isinstance(value,dict):
        for k,v in value.items():
            if "cost" in k and (not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<0): errors.append(f"{path}: invalid cost")
            _costs(v,path,errors)
    elif isinstance(value,list):
        for x in value:_costs(x,path,errors)

def validate_all(output:Path,generated:Path=Path("generated"),storage=None,public_base:str="",max_candidates:int=60,expected_editorial_model:str|None=None,expected_image_model:str|None=None,max_provider_image_bytes:int=12_000_000,max_image_pixels:int=20_000_000,max_image_bytes:int=2_000_000)->list[str]:
    errors=[]
    if output.is_symlink(): return ["output: symlink not permitted"]
    mpath=output/"manifest.json"
    if not mpath.exists():
        unexpected=[p for p in output.rglob("*") if p.is_file() or p.is_symlink()] if output.exists() else []
        return [f"manifest missing with unexpected file: {p.relative_to(output)}" for p in unexpected]
    try: manifest=json.loads(mpath.read_text(encoding="utf-8"))
    except Exception: return ["manifest: invalid JSON"]
    if set(manifest)!={"schema_version","generator_version","dates"} or manifest.get("schema_version")!=SCHEMA_VERSION or not isinstance(manifest.get("dates"),list): errors.append("manifest: invalid contract"); return errors
    dates=[]; referenced=set()
    for e in manifest["dates"]:
        date=e.get("date"); rel=e.get("file"); dates.append(date)
        try: path=contained_path(output,rel); referenced.add(path.resolve())
        except Exception: errors.append(f"{date}: unsafe artifact path"); continue
        if rel!=artifact_relative(date): errors.append(f"{date}: date/path mismatch")
        try: raw=path.read_bytes(); a=json.loads(raw)
        except Exception: errors.append(f"{date}: artifact missing or invalid"); continue
        if canonical_bytes(a)!=raw: errors.append(f"{date}: non-canonical JSON")
        if e.get("sha256")!=sha256_bytes(raw) or e.get("bytes")!=len(raw): errors.append(f"{date}: artifact checksum mismatch")
        legacy={"schema_version","generator_version","date","status","editorial_input_hash","illustration_input_hash","generated_at","prompt_versions","models","plan","illustration","usage","generation"};v2=legacy|{"illustration_profile_id","visual_brief_schema_version"}
        if set(a) not in (legacy,v2) or a.get("date")!=date or a.get("schema_version")!=SCHEMA_VERSION: errors.append(f"{date}: invalid artifact contract")
        is_v2=a.get("prompt_versions",{}).get("illustration")=="2.0.0";brief=a.get("plan",{}).get("visual_brief",{});brief_v2=brief.get("schema_version")=="2.0.0"
        if is_v2 and (set(a)!=v2 or a.get("illustration_profile_id")!="production-v2" or a.get("visual_brief_schema_version")!="2.0.0" or not brief_v2): errors.append(f"{date}: invalid v2 illustration metadata")
        if not is_v2 and (set(a)!=legacy or brief_v2):errors.append(f"{date}: invalid historical illustration metadata")
        if brief_v2:
            expected_brief={"schema_version","mode","sources","editorial_idea","central_subject","visual_relationship","composition","literal_elements","abstraction_level","forbidden_elements","failure_modes","alt_text"}
            if set(brief)!=expected_brief or brief.get("abstraction_level") not in ("low","medium","high"):errors.append(f"{date}: invalid v2 visual brief")
            for key,limit in (("literal_elements",12),("forbidden_elements",20),("failure_modes",12)):
                value=brief.get(key);valid=isinstance(value,list) and len(value)<=limit and all(isinstance(x,str) and x.strip() and len(x)<=100 for x in value) and len(value)==len(set(value))
                if not valid:errors.append(f"{date}: invalid v2 visual brief {key}")
            if not isinstance(brief.get("sources"),list) or not brief["sources"] or len(brief["sources"])>3 or any(not isinstance(x,dict) or set(x)!={"issue_id","article_id"} for x in brief.get("sources",[])):errors.append(f"{date}: invalid v2 visual brief sources")
        if a.get("status") not in ("ai_complete","editorial_only","deterministic_fallback","disabled"): errors.append(f"{date}: invalid status")
        if e.get("status")!=a.get("status") or e.get("editorial_input_hash")!=a.get("editorial_input_hash") or e.get("illustration_input_hash")!=a.get("illustration_input_hash"): errors.append(f"{date}: manifest/artifact status or hash mismatch")
        if not isinstance(a.get("models"),dict) or set(a["models"])!={"editorial","illustration"} or not all(isinstance(x,str) and x for x in a["models"].values()): errors.append(f"{date}: invalid models")
        if not isinstance(a.get("prompt_versions"),dict) or set(a["prompt_versions"])!={"editorial","illustration"} or not all(isinstance(x,str) and re.fullmatch(r"\d+\.\d+\.\d+",x) for x in a["prompt_versions"].values()): errors.append(f"{date}: invalid prompt versions")
        if not SHA_RE.fullmatch(str(a.get("editorial_input_hash",""))): errors.append(f"{date}: invalid editorial hash")
        ih=a.get("illustration_input_hash")
        if ih is not None and not SHA_RE.fullmatch(str(ih)): errors.append(f"{date}: invalid illustration hash")
        by={};bounded_by={}
        try:
            source=load_date(generated,date); bounded=shortlist(source,max_candidates)
            by={(c.issue_id,c.article_id):c for c in source}; bounded_by={(c.issue_id,c.article_id):c for c in bounded}
            declared_editorial=a.get("models",{}).get("editorial")
            expected_hash=hash_parts(dossier(bounded),declared_editorial,EDITORIAL_PROMPT_VERSION,EDITORIAL_SCHEMA_VERSION)
            if a.get("editorial_input_hash")!=expected_hash: errors.append(f"{date}: stale editorial input hash")
            if a.get("prompt_versions",{}).get("editorial")!=EDITORIAL_PROMPT_VERSION: errors.append(f"{date}: editorial prompt version mismatch")
            if is_v2 and a.get("prompt_versions",{}).get("illustration")!=ILLUSTRATION_PROMPT_VERSION: errors.append(f"{date}: illustration prompt version mismatch")
            if expected_editorial_model and declared_editorial!=expected_editorial_model: errors.append(f"{date}: configured editorial model mismatch")
            if expected_image_model and a.get("models",{}).get("illustration")!=expected_image_model: errors.append(f"{date}: configured illustration model mismatch")
        except (EditorialError,KeyError,TypeError):
            errors.append(f"{date}: source data invalid")
        fp=a.get("plan",{}).get("front_page",[])
        roles=[]
        for item in fp:
            c=by.get((item.get("issue_id"),item.get("article_id"))); roles.append(item.get("role"))
            if c is None: errors.append(f"{date}: source reference missing")
            elif not c.front_page_eligible: errors.append(f"{date}: ineligible source selected")
        if fp and (roles.count("lead")!=1 or roles.count("secondary")>4 or len(fp)>9): errors.append(f"{date}: invalid role counts")
        if ih is not None and bounded_by:
            vb=a.get("plan",{}).get("visual_brief",{})
            try:
                source_ids=[bounded_by[(x["issue_id"],x["article_id"])] for x in vb["sources"]]
                keys=("schema_version","editorial_idea","central_subject","visual_relationship","composition","literal_elements","abstraction_level","forbidden_elements","failure_modes","alt_text") if vb.get("schema_version")=="2.0.0" else ("central_subject","visual_metaphor","composition","forbidden_elements","alt_text")
                hash_brief={"mode":vb["mode"],"source_candidate_ids":[x.candidate_id for x in source_ids],**{k:vb[k] for k in keys}}
                image_cfg=image_configuration(max_provider_image_bytes,max_image_pixels,max_image_bytes)
                version=a["prompt_versions"]["illustration"];facts=[{"issue_id":c.issue_id,"article_id":c.article_id,"title":c.title,"summary":c.summary} for c in source_ids]
                expected_ih=illustration_input_hash(brief=hash_brief,sources=facts,image_model=a["models"]["illustration"],prompt_version=version,image_config=image_cfg,profile=get_profile("production-v2") if version=="2.0.0" else None)
                if ih!=expected_ih: errors.append(f"{date}: stale illustration input hash")
            except (KeyError,TypeError): errors.append(f"{date}: illustration hash inputs unavailable")
        ill=a.get("illustration",{}); status=ill.get("status")
        allowed=("ready","not_requested","disabled","generation_failed","validation_failed","upload_failed","storage_verification_failed")
        if status not in allowed: errors.append(f"{date}: invalid illustration status")
        if status=="ready":
            if is_v2 and (ih is None or not SHA_RE.fullmatch(str(a.get("generation",{}).get("final_prompt_sha256","")))):errors.append(f"{date}: incomplete v2 prompt metadata")
            try:
                validate_object_key(ill.get("object_key"),date)
                if ill["object_key"].rsplit("/",1)[1][:-5] != str(ill.get("sha256","")).removeprefix("sha256:"): errors.append(f"{date}: object key/SHA mismatch")
            except Exception: errors.append(f"{date}: invalid object key")
            if not (SHA_RE.fullmatch(str(ill.get("sha256",""))) and isinstance(ill.get("bytes"),int) and ill["bytes"]>0 and isinstance(ill.get("width"),int) and ill["width"]>0 and isinstance(ill.get("height"),int) and ill["height"]>0 and ill.get("media_type")=="image/webp" and ill.get("storage_verified") is True): errors.append(f"{date}: incomplete ready image")
            url=ill.get("public_url","")
            if not isinstance(url,str) or not url.startswith("https://") or not url.endswith("/"+ill.get("object_key","")): errors.append(f"{date}: invalid public URL")
            if public_base and url!=public_base.rstrip("/")+"/"+ill.get("object_key",""): errors.append(f"{date}: public URL/base mismatch")
            if any((e.get("illustration_status")!=status,e.get("illustration_object_key")!=ill.get("object_key"),e.get("illustration_public_url")!=ill.get("public_url"),e.get("illustration_sha256")!=ill.get("sha256"),e.get("illustration_bytes")!=ill.get("bytes"))): errors.append(f"{date}: manifest/image identity mismatch")
            if storage:
                try: storage.verify_object(ill["object_key"],size=ill["bytes"],sha256=ill["sha256"])
                except EditorialError: errors.append(f"{date}: live storage verification failed")
        elif any(e.get(k) is not None for k in ("illustration_object_key","illustration_public_url","illustration_sha256","illustration_bytes")) or e.get("illustration_status")!=status:
            errors.append(f"{date}: stale manifest image identity")
        _costs(a,date,errors)
        blob=json.dumps(a).lower()
        if re.search(r"(authorization|secret_access_key|api_key)[\"']?\s*:",blob) or "/users/" in blob or "/home/" in blob: errors.append(f"{date}: secret-like or absolute path material")
    if len(dates)!=len(set(dates)) or dates!=sorted(dates): errors.append("manifest: duplicate or unsorted dates")
    for p in output.rglob("*"):
        if p.name.startswith(".tldr-editorial-") or p.suffix==".tmp": errors.append(f"orphan temporary file: {p.name}")
        if p.is_file() and p.name!="manifest.json" and p.resolve() not in referenced: errors.append(f"orphan artifact: {p.relative_to(output)}")
    return errors
