"""Strict local editorial-plan validation and deterministic fallback."""
from __future__ import annotations
import json,re
from typing import Any
from .candidates import Candidate, sector_key
from .core import EditorialError

ROLES={"lead","secondary","brief"}; MODES={"lead_story","edition_theme","none"}
PLAN_KEYS={"lead_candidate_id","front_page","section_order","visual_brief"}
V1_VISUAL_KEYS={"mode","source_candidate_ids","central_subject","visual_metaphor","composition","forbidden_elements","alt_text"}
V2_VISUAL_KEYS={"schema_version","mode","source_candidate_ids","editorial_idea","central_subject","visual_relationship","composition","literal_elements","abstraction_level","forbidden_elements","failure_modes","alt_text"}
CONTROL=re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
PROHIBITED=re.compile(r"https?://|<[^>]+>|\[[^]]+\]\([^)]+\)",re.I)

def _text(value: Any, name: str, maximum: int=500, allow_empty: bool=False) -> str:
    if not isinstance(value,str) or (not allow_empty and not value.strip()) or len(value)>maximum or CONTROL.search(value) or PROHIBITED.search(value):
        raise EditorialError(f"plan_invalid_{name}")
    return value.strip()

def parse_plan_content(content: str) -> dict:
    if not isinstance(content,str): raise EditorialError("plan_content_missing")
    try: value=json.loads(content)
    except json.JSONDecodeError as exc: raise EditorialError("plan_malformed_json") from exc
    if not isinstance(value,dict): raise EditorialError("plan_not_object")
    return value

def validate_plan(plan: dict, candidates: list[Candidate]) -> dict:
    if not isinstance(plan,dict) or set(plan)!=PLAN_KEYS: raise EditorialError("plan_unknown_properties")
    by_id={c.candidate_id:c for c in candidates}; eligible=[c for c in candidates if c.front_page_eligible]
    lead=_text(plan["lead_candidate_id"],"lead_id",16)
    fp=plan["front_page"]
    expected=min(9,len(eligible))
    if not isinstance(fp,list) or len(fp)!=expected: raise EditorialError("plan_front_page_count")
    selected=[]; roles=[]
    for item in fp:
        if not isinstance(item,dict) or set(item)!={"candidate_id","role"}: raise EditorialError("plan_entry_properties")
        cid=_text(item["candidate_id"],"candidate_id",16); role=item["role"]
        if role not in ROLES: raise EditorialError("plan_role")
        c=by_id.get(cid)
        if c is None: raise EditorialError("plan_unknown_candidate")
        if not c.front_page_eligible: raise EditorialError("plan_ineligible_candidate")
        selected.append(cid); roles.append(role)
    if len(set(selected))!=len(selected): raise EditorialError("plan_duplicate_candidate")
    if roles.count("lead")!=1 or selected[roles.index("lead")]!=lead: raise EditorialError("plan_lead")
    if roles.count("secondary")>4: raise EditorialError("plan_secondary_count")
    sections=plan["section_order"]
    present={c.sector_slug for c in candidates}
    if not isinstance(sections,list) or len(sections)>len(present) or len(set(sections))!=len(sections) or any(not isinstance(x,str) or x not in present for x in sections):
        raise EditorialError("plan_section_order")
    vb=plan["visual_brief"]
    if not isinstance(vb,dict) or set(vb) not in (V1_VISUAL_KEYS,V2_VISUAL_KEYS): raise EditorialError("plan_visual_properties")
    mode=vb["mode"]
    if mode not in MODES: raise EditorialError("plan_visual_mode")
    src=vb["source_candidate_ids"]
    if not isinstance(src,list) or len(src)>3 or len(set(src))!=len(src) or any(x not in selected for x in src): raise EditorialError("plan_visual_sources")
    if mode=="none" and src: raise EditorialError("plan_visual_none_sources")
    if mode!="none" and not src: raise EditorialError("plan_visual_sources")
    if mode=="lead_story" and src != [lead]: raise EditorialError("plan_lead_visual_source")
    cleaned={"mode":mode,"source_candidate_ids":src}
    v2=set(vb)==V2_VISUAL_KEYS
    if v2:
        if vb["schema_version"]!="2.0.0":raise EditorialError("plan_visual_schema_version")
        cleaned["schema_version"]="2.0.0"
        for k,maxlen in (("editorial_idea",500),("central_subject",300),("visual_relationship",500),("composition",500),("alt_text",500)):
            cleaned[k]=_text(vb[k],k,maxlen,allow_empty=mode=="none")
        if vb["abstraction_level"] not in ("low","medium","high"):raise EditorialError("plan_abstraction_level")
        cleaned["abstraction_level"]=vb["abstraction_level"]
        for k,limit in (("literal_elements",12),("forbidden_elements",20),("failure_modes",12)):
            value=vb[k]
            if not isinstance(value,list) or len(value)>limit:raise EditorialError("plan_"+k)
            cleaned[k]=[_text(x,k[:-1],100) for x in value]
            if len(set(cleaned[k]))!=len(cleaned[k]):raise EditorialError("plan_"+k)
    else:
        for k,maxlen in (("central_subject",300),("visual_metaphor",500),("composition",500),("alt_text",500)):
            cleaned[k]=_text(vb[k],k,maxlen,allow_empty=mode=="none")
    if not v2:
        forbidden=vb["forbidden_elements"]
        if not isinstance(forbidden,list) or len(forbidden)>20: raise EditorialError("plan_forbidden_elements")
        cleaned["forbidden_elements"]=[_text(x,"forbidden_element",100) for x in forbidden]
    if re.search(r"\b(photo|photograph|photographic)\b",cleaned["alt_text"],re.I): raise EditorialError("plan_alt_text_photo")
    return {"lead_candidate_id":lead,"front_page":[{"candidate_id":c,"role":r} for c,r in zip(selected,roles)],"section_order":sections,"visual_brief":cleaned}

def fallback(candidates: list[Candidate]) -> dict:
    eligible=[c for c in candidates if c.front_page_eligible]
    if not eligible:
        return {"lead_candidate_id":None,"front_page":[],"section_order":[],"visual_brief":{"mode":"none","source_candidate_ids":[],"central_subject":"","visual_metaphor":"","composition":"","forbidden_elements":[],"alt_text":""}}
    lead=next((c for c in eligible if c.sector_slug=="tldr"),eligible[0]); remaining=[c for c in eligible if c!=lead]
    selected=[lead]; used={lead.sector_slug}
    distinct=[c for c in remaining if c.sector_slug not in used]
    secondaries=[]
    for c in distinct:
        if c.sector_slug not in used and len(secondaries)<4: secondaries.append(c); used.add(c.sector_slug)
    for c in remaining:
        if len(secondaries)>=4: break
        if c not in secondaries: secondaries.append(c)
    selected += secondaries
    selected += [c for c in remaining if c not in secondaries][:9-len(selected)]
    roles=["lead"]+["secondary"]*len(secondaries)+["brief"]*(len(selected)-1-len(secondaries))
    sections=[]
    for c in selected:
        if c.sector_slug not in sections: sections.append(c.sector_slug)
    return {"lead_candidate_id":lead.candidate_id,"front_page":[{"candidate_id":c.candidate_id,"role":r} for c,r in zip(selected,roles)],"section_order":sections,
            "visual_brief":{"mode":"none","source_candidate_ids":[],"central_subject":"","visual_metaphor":"","composition":"","forbidden_elements":[],"alt_text":""}}

def resolve_plan(plan: dict,candidates:list[Candidate]) -> dict:
    by={c.candidate_id:c for c in candidates}
    def ref(cid):
        c=by[cid]; return {"issue_id":c.issue_id,"article_id":c.article_id}
    lead=ref(plan["lead_candidate_id"]) if plan["lead_candidate_id"] else None
    fp=[{**ref(x["candidate_id"]),"role":x["role"]} for x in plan["front_page"]]
    vb=plan["visual_brief"]
    keys=("schema_version","editorial_idea","central_subject","visual_relationship","composition","literal_elements","abstraction_level","forbidden_elements","failure_modes","alt_text") if vb.get("schema_version")=="2.0.0" else ("central_subject","visual_metaphor","composition","forbidden_elements","alt_text")
    return {"lead":lead,"front_page":fp,"section_order":plan["section_order"],"visual_brief":{"mode":vb["mode"],"sources":[ref(x) for x in vb["source_candidate_ids"]],**{k:vb[k] for k in keys}}}
