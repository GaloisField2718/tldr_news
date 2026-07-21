"""Small fixed-host OpenRouter client; errors intentionally contain no response bodies."""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any, Callable
from .config import Config
from .core import EditorialError
from .plan import parse_plan_content

API_URL="https://openrouter.ai/api/v1/chat/completions"

PLAN_SCHEMA={"type":"object","additionalProperties":False,"required":["lead_candidate_id","front_page","section_order","visual_brief"],"properties":{
 "lead_candidate_id":{"type":"string","pattern":"^c[0-9]{3}$"},
 "front_page":{"type":"array","maxItems":9,"items":{"type":"object","additionalProperties":False,"required":["candidate_id","role"],"properties":{"candidate_id":{"type":"string","pattern":"^c[0-9]{3}$"},"role":{"enum":["lead","secondary","brief"]}}}},
 "section_order":{"type":"array","maxItems":20,"items":{"type":"string","maxLength":80}},
 "visual_brief":{"type":"object","additionalProperties":False,"required":["mode","source_candidate_ids","central_subject","visual_metaphor","composition","forbidden_elements","alt_text"],"properties":{
  "mode":{"enum":["lead_story","edition_theme","none"]},"source_candidate_ids":{"type":"array","maxItems":3,"items":{"type":"string","pattern":"^c[0-9]{3}$"}},
  "central_subject":{"type":"string","maxLength":300},"visual_metaphor":{"type":"string","maxLength":500},"composition":{"type":"string","maxLength":500},
  "forbidden_elements":{"type":"array","maxItems":20,"items":{"type":"string","maxLength":100}},"alt_text":{"type":"string","maxLength":500}}}}}

@dataclass(frozen=True)
class Result:
    value: Any
    usage: dict
    request_id: str | None


def _usage(doc: dict) -> dict:
    u=doc.get("usage") if isinstance(doc.get("usage"),dict) else {}
    def number(key, integer=False):
        v=u.get(key,0)
        if not isinstance(v,(int,float)) or isinstance(v,bool) or v<0: return 0 if integer else 0.0
        return int(v) if integer else float(v)
    return {"prompt_tokens":number("prompt_tokens",True),"completion_tokens":number("completion_tokens",True),"total_tokens":number("total_tokens",True),"cost_usd":number("cost",False)}

def _default_post(*args, **kwargs):
    import requests  # Locked dependency; lazy so fully mocked/offline tests need no install.
    return requests.post(*args, **kwargs)

class OpenRouterClient:
    def __init__(self,config:Config,post:Callable[...,Any]|None=None): self.config=config; self._post=post or _default_post
    def _headers(self)->dict:
        h={"Authorization":f"Bearer {self.config.api_key}","Content-Type":"application/json","X-Title":self.config.app_title}
        if self.config.http_referer: h["HTTP-Referer"]=self.config.http_referer
        return h
    def _request(self,body:dict,timeout:int)->dict:
        # A conservative bound prevents accidental historical-corpus transmission.
        if len(json.dumps(body,ensure_ascii=False).encode())>500_000: raise EditorialError("openrouter_request_too_large")
        try: r=self._post(API_URL,headers=self._headers(),json=body,timeout=timeout)
        except Exception as exc: raise EditorialError("openrouter_transport_failed") from exc
        if not 200<=r.status_code<300: raise EditorialError(f"openrouter_http_{r.status_code}")
        try: doc=r.json()
        except (ValueError,json.JSONDecodeError) as exc: raise EditorialError("openrouter_malformed_json") from exc
        if not isinstance(doc,dict): raise EditorialError("openrouter_invalid_response")
        return doc
    def editorial(self,dossier:list[dict])->Result:
        system=("Select and organize this date's technology front page. Return only the schema object. "
                "Never rewrite titles or summaries, select sponsors or resources, invent facts, emit markup, or reveal reasoning.")
        body={"model":self.config.editorial_model,"stream":False,"messages":[{"role":"system","content":system},{"role":"user","content":json.dumps({"candidates":dossier},ensure_ascii=False,separators=(",",":"))}],
              "response_format":{"type":"json_schema","json_schema":{"name":"daily_editorial_plan","strict":True,"schema":PLAN_SCHEMA}},
              "provider":{"require_parameters":True},"reasoning":{"effort":"low","exclude":True}}
        doc=self._request(body,self.config.editorial_timeout)
        choices=doc.get("choices")
        if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict): raise EditorialError("openrouter_missing_choices")
        message=choices[0].get("message")
        if not isinstance(message,dict): raise EditorialError("openrouter_missing_message")
        value=parse_plan_content(message.get("content"))
        return Result(value,_usage(doc),doc.get("id") if isinstance(doc.get("id"),str) else None)
    def image(self,prompt:str)->Result:
        body={"model":self.config.image_model,"stream":False,"modalities":["image"],"messages":[{"role":"user","content":prompt}],"n":1,
              "image_config":{"resolution":"1K","aspect_ratio":"3:2","output_format":"webp","output_compression":82,"background":"opaque"}}
        doc=self._request(body,self.config.image_timeout)
        choices=doc.get("choices")
        if not isinstance(choices,list) or len(choices)!=1: raise EditorialError("image_missing_choices")
        msg=choices[0].get("message",{}) if isinstance(choices[0],dict) else {}
        images=msg.get("images")
        if not isinstance(images,list) or len(images)!=1: raise EditorialError("image_count_invalid")
        image=images[0]
        if not isinstance(image,dict): raise EditorialError("image_response_invalid")
        value=image.get("b64_json")
        if not isinstance(value,str):
            value=(image.get("image_url") or {}).get("url") if isinstance(image.get("image_url"),dict) else None
        if not isinstance(value,str): raise EditorialError("image_data_missing")
        return Result(value,_usage(doc),doc.get("id") if isinstance(doc.get("id"),str) else None)
