"""Canonical version-aware illustration semantic hashing."""
from __future__ import annotations
from .core import hash_parts
from .illustration_prompts import PromptProfile

def illustration_input_hash(*,brief:dict,sources:list[dict],image_model:str,prompt_version:str,image_config:dict,profile:PromptProfile|None=None)->str:
    """Hash only inputs that can change the requested image; preserve the v1 contract."""
    if prompt_version=="1.0.0":
        return hash_parts(brief,[{"title":x["title"],"summary":x["summary"]} for x in sources],image_model,prompt_version,image_config)
    if prompt_version!="2.0.0" or profile is None:raise ValueError("unsupported_illustration_hash_contract")
    profile_contract={"profile_id":profile.profile_id,"internal_id":profile.internal_id,"schema_version":profile.schema_version,"preamble":profile.preamble,"fixed_negative_constraints":list(profile.fixed_negative_constraints),"rendering_material_constraints":list(profile.rendering_material_constraints),"shared_factual_restrictions":list(profile.shared_factual_restrictions)}
    facts=[{"issue_id":x["issue_id"],"article_id":x["article_id"],"title":x["title"],"summary":x["summary"]} for x in sources]
    return hash_parts({"illustration_profile":profile_contract,"illustration_prompt_version":prompt_version,"visual_brief_schema_version":brief.get("schema_version"),"visual_brief":brief,"exact_sources":facts,"image_model":image_model,"image_configuration":image_config})
