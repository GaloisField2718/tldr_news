"""Deterministic prompt assembly and strict WebP binary validation."""
from __future__ import annotations
import base64,binascii,hashlib,re,struct
from dataclasses import dataclass
from .candidates import Candidate
from .core import EditorialError

PREAMBLE="""Create a premium editorial illustration for a serious technology newspaper.

The image is an editorial illustration, not documentary photography.
Use one immediately readable focal subject.
Use a strong, restrained composition with controlled contrast.
Use sophisticated but understandable visual symbolism.
Leave useful negative space around the focal subject.
Do not render words, captions, headlines, logos, trademarks, interfaces, screenshots, charts, watermarks, or newspaper typography.
Do not fabricate visible factual evidence.
Do not imitate a named or living illustrator.
Do not create a collage of unrelated news stories.
The image must remain readable at newspaper-column and social-card sizes."""

@dataclass(frozen=True)
class ValidatedImage:
    data: bytes
    width: int
    height: int
    media_type: str
    sha256: str
    @property
    def bytes(self)->int: return len(self.data)

def assemble_prompt(brief:dict,source_candidates:list[Candidate])->str:
    lines=[PREAMBLE,"","Source stories (use only these facts):"]
    for c in source_candidates: lines += [f"Title: {c.title}",f"Summary: {c.summary}"]
    lines += ["",f"Central subject: {brief['central_subject']}",f"Visual metaphor: {brief['visual_metaphor']}",f"Composition: {brief['composition']}",
              "Forbidden elements: "+(", ".join(brief["forbidden_elements"]) or "none beyond the fixed restrictions")]
    return "\n".join(lines).strip()+"\n"

def decode_image(value:str,provider_media_type:str|None=None)->tuple[bytes,str]:
    media=(provider_media_type or "image/webp").lower(); raw=value
    if value.startswith("data:"):
        m=re.fullmatch(r"data:([^;,]+);base64,(.+)",value,re.S)
        if not m: raise EditorialError("image_data_url_invalid")
        embedded=m.group(1).lower()
        if provider_media_type and embedded!=media: raise EditorialError("image_media_type_mismatch")
        media=embedded; raw=m.group(2)
    try: data=base64.b64decode(raw,validate=True)
    except (ValueError,binascii.Error) as exc: raise EditorialError("image_base64_invalid") from exc
    return data,media

def webp_dimensions(data:bytes)->tuple[int,int]:
    if len(data)<30 or data[:4]!=b"RIFF" or data[8:12]!=b"WEBP": raise EditorialError("image_webp_malformed")
    declared=struct.unpack_from("<I",data,4)[0]+8
    if declared!=len(data): raise EditorialError("image_webp_malformed")
    kind=data[12:16]
    if kind==b"VP8X":
        w=1+int.from_bytes(data[24:27],"little"); h=1+int.from_bytes(data[27:30],"little")
    elif kind==b"VP8 ":
        pos=data.find(b"\x9d\x01\x2a",20,40)
        if pos<0 or len(data)<pos+7: raise EditorialError("image_webp_malformed")
        w=struct.unpack_from("<H",data,pos+3)[0]&0x3fff; h=struct.unpack_from("<H",data,pos+5)[0]&0x3fff
    elif kind==b"VP8L":
        if data[20]!=0x2f: raise EditorialError("image_webp_malformed")
        bits=int.from_bytes(data[21:25],"little"); w=(bits&0x3fff)+1; h=((bits>>14)&0x3fff)+1
    else: raise EditorialError("image_webp_malformed")
    return w,h

def validate_image(data:bytes,media_type:str,max_bytes:int)->ValidatedImage:
    if not data: raise EditorialError("image_empty")
    if len(data)>max_bytes: raise EditorialError("image_too_large")
    if media_type.lower()!="image/webp": raise EditorialError("image_media_type_invalid")
    w,h=webp_dimensions(data)
    if not (256<=w<=8192 and 256<=h<=8192): raise EditorialError("image_dimensions_unreasonable")
    if abs((w/h)-1.5)/1.5>0.08: raise EditorialError("image_aspect_ratio_invalid")
    return ValidatedImage(data,w,h,"image/webp","sha256:"+hashlib.sha256(data).hexdigest())
