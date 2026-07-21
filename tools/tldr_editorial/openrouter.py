"""Bounded fixed-host OpenRouter chat and dedicated Images API client."""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any, Callable
from .config import Config
from .core import EditorialError
from .plan import parse_plan_content

CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
IMAGE_MODELS_URL = "https://openrouter.ai/api/v1/images/models"
IMAGE_GENERATION_URL = "https://openrouter.ai/api/v1/images"
EDITORIAL_RESPONSE_MAX_BYTES = 256_000
CAPABILITY_RESPONSE_MAX_BYTES = 2_000_000

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
    media_type: str | None = None


def _usage(doc:dict)->dict:
    u=doc.get("usage") if isinstance(doc.get("usage"),dict) else {}
    def number(key,integer=False):
        v=u.get(key,0)
        if not isinstance(v,(int,float)) or isinstance(v,bool) or v<0:return 0 if integer else 0.0
        return int(v) if integer else float(v)
    return {"prompt_tokens":number("prompt_tokens",True),"completion_tokens":number("completion_tokens",True),"total_tokens":number("total_tokens",True),"cost_usd":number("cost",False)}

def _request_id(doc:dict)->str|None:
    value=doc.get("id")
    return value if isinstance(value,str) and 0<len(value)<=256 and all(32<=ord(c)<127 for c in value) else None

def _default_post(*args,**kwargs):
    import requests
    return requests.post(*args,**kwargs)

def _default_get(*args,**kwargs):
    import requests
    return requests.get(*args,**kwargs)

def _bounded_json(response,max_bytes:int,oversize_code:str)->dict:
    headers=getattr(response,"headers",{}) or {}
    try:length=int(headers.get("Content-Length",0))
    except (TypeError,ValueError):length=0
    if length>max_bytes:raise EditorialError(oversize_code)
    raw=None
    if hasattr(response,"iter_content"):
        chunks=[];total=0
        for chunk in response.iter_content(chunk_size=65_536):
            if not chunk:continue
            total+=len(chunk)
            if total>max_bytes:raise EditorialError(oversize_code)
            chunks.append(chunk)
        raw=b"".join(chunks)
    elif isinstance(getattr(response,"content",None),(bytes,bytearray)):
        raw=bytes(response.content)
        if len(raw)>max_bytes:raise EditorialError(oversize_code)
    try:
        doc=json.loads(raw.decode("utf-8")) if raw is not None else response.json()
    except (UnicodeDecodeError,ValueError,json.JSONDecodeError) as exc:raise EditorialError("openrouter_malformed_json") from exc
    if raw is None and len(json.dumps(doc,ensure_ascii=False).encode("utf-8"))>max_bytes:raise EditorialError(oversize_code)
    if not isinstance(doc,dict):raise EditorialError("openrouter_invalid_response")
    return doc

def _supports(spec:Any,value:Any)->bool:
    if not isinstance(spec,dict):return False
    if spec.get("type")=="enum":return value in spec.get("values",[])
    if spec.get("type")=="range" and isinstance(value,(int,float)):return spec.get("min",value)<=value<=spec.get("max",value)
    if spec.get("type")=="boolean":return isinstance(value,bool)
    return False

class OpenRouterClient:
    def __init__(self,config:Config,post:Callable[...,Any]|None=None,get:Callable[...,Any]|None=None):
        self.config=config;self._post=post or _default_post;self._get=get or _default_get;self._image_capability=None
    def _headers(self)->dict:
        h={"Authorization":f"Bearer {self.config.api_key}","Content-Type":"application/json","X-Title":self.config.app_title}
        if self.config.http_referer:h["HTTP-Referer"]=self.config.http_referer
        return h
    def _response(self,method:Callable[...,Any],url:str,timeout:int,max_bytes:int,oversize_code:str,body:dict|None=None)->dict:
        if not url.startswith("https://openrouter.ai/api/v1/"):raise EditorialError("openrouter_host_invalid")
        if body is not None and len(json.dumps(body,ensure_ascii=False).encode())>500_000:raise EditorialError("openrouter_request_too_large")
        try:
            kwargs={"headers":self._headers(),"timeout":timeout}
            if body is not None:kwargs["json"]=body
            response=method(url,**kwargs)
        except Exception as exc:raise EditorialError("openrouter_transport_failed") from exc
        if not 200<=response.status_code<300:raise EditorialError(f"openrouter_http_{response.status_code}")
        return _bounded_json(response,max_bytes,oversize_code)
    def editorial(self,dossier:list[dict])->Result:
        eligible=sum(x.get("content_class")=="editorial" and bool(x.get("title")) and bool(x.get("summary")) for x in dossier)
        expected=min(9,eligible)
        system=("Organize the supplied technology dossier into the strict front-page JSON object. "
          f"Select exactly {expected} front-page stories (expected_front_page_count). Use exactly one lead, no more than four secondaries, and make all remaining stories briefs. "
          "Every candidate ID must come from the supplied dossier; lead_candidate_id must identify the entry whose role is lead. "
          "section_order may contain unique present sectors only. A lead_story visual source is exactly the lead. "
          "An edition_theme uses exactly two or three genuinely related selected stories. none uses no sources and empty semantic fields. "
          "Never rewrite titles or summaries, select sponsors or resources, invent facts, emit URLs, markup, prose, or reasoning. Return only the strict JSON object.")
        user={"request_metadata":{"expected_front_page_count":expected,"eligible_candidate_count":eligible},"candidates":dossier}
        body={"model":self.config.editorial_model,"stream":False,"messages":[{"role":"system","content":system},{"role":"user","content":json.dumps(user,ensure_ascii=False,separators=(",",":"))}],
          "response_format":{"type":"json_schema","json_schema":{"name":"daily_editorial_plan","strict":True,"schema":PLAN_SCHEMA}},"provider":{"require_parameters":True},"reasoning":{"effort":"low","exclude":True}}
        doc=self._response(self._post,CHAT_COMPLETIONS_URL,self.config.editorial_timeout,EDITORIAL_RESPONSE_MAX_BYTES,"editorial_response_too_large",body)
        choices=doc.get("choices")
        if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict):raise EditorialError("openrouter_missing_choices")
        message=choices[0].get("message")
        if not isinstance(message,dict):raise EditorialError("openrouter_missing_message")
        return Result(parse_plan_content(message.get("content")),_usage(doc),_request_id(doc))
    def image_capability(self)->dict:
        if self._image_capability is not None:return self._image_capability
        models=self._response(self._get,IMAGE_MODELS_URL,self.config.editorial_timeout,CAPABILITY_RESPONSE_MAX_BYTES,"image_capability_response_too_large")
        entries=models.get("data")
        if not isinstance(entries,list):raise EditorialError("image_models_invalid")
        model=next((x for x in entries if isinstance(x,dict) and x.get("id")==self.config.image_model),None)
        if model is None:raise EditorialError("image_model_unavailable")
        relative=model.get("endpoints")
        expected=f"/api/v1/images/models/{self.config.image_model}/endpoints"
        if relative!=expected:raise EditorialError("image_endpoints_path_invalid")
        endpoint_doc=self._response(self._get,"https://openrouter.ai"+relative,self.config.editorial_timeout,CAPABILITY_RESPONSE_MAX_BYTES,"image_capability_response_too_large")
        endpoints=endpoint_doc.get("endpoints")
        if not isinstance(endpoints,list):raise EditorialError("image_endpoints_invalid")
        selected=None
        for endpoint in endpoints:
            params=endpoint.get("supported_parameters",{}) if isinstance(endpoint,dict) else {}
            if (_supports(params.get("n"),1) and _supports(params.get("resolution"),"1K") and _supports(params.get("aspect_ratio"),"3:2") and _supports(params.get("output_format"),"webp")):
                selected=endpoint;break
        if selected is None:raise EditorialError("image_required_capability_absent")
        self._image_capability=selected
        return selected
    def image(self,prompt:str)->Result:
        endpoint=self.image_capability();params=endpoint["supported_parameters"]
        body={"model":self.config.image_model,"prompt":prompt,"n":1,"resolution":"1K","aspect_ratio":"3:2","output_format":"webp"}
        if _supports(params.get("output_compression"),82):body["output_compression"]=82
        if _supports(params.get("background"),"opaque"):body["background"]="opaque"
        slug=endpoint.get("provider_slug")
        if isinstance(slug,str) and slug:body["provider"]={"only":[slug],"allow_fallbacks":False}
        max_response=((self.config.max_image_bytes+2)//3)*4+262_144
        doc=self._response(self._post,IMAGE_GENERATION_URL,self.config.image_timeout,max_response,"image_response_too_large",body)
        data=doc.get("data")
        if not isinstance(data,list) or len(data)!=1:raise EditorialError("image_count_invalid")
        image=data[0]
        if not isinstance(image,dict) or not isinstance(image.get("b64_json"),str):raise EditorialError("image_data_missing")
        media=image.get("media_type")
        if media is not None and not isinstance(media,str):raise EditorialError("image_media_type_invalid")
        return Result(image["b64_json"],_usage(doc),_request_id(doc),media)
