"""Deterministic prompt assembly and strict WebP binary validation."""
from __future__ import annotations
import base64,binascii,hashlib,io,re,struct,warnings
from pathlib import Path
from dataclasses import dataclass
from .candidates import Candidate
from .core import EditorialError,WEBP_METHOD,WEBP_QUALITY
from .illustration_prompts import BASELINE_PROFILE,PromptProfile

@dataclass(frozen=True)
class ValidatedImage:
    data: bytes
    width: int
    height: int
    media_type: str
    sha256: str
    @property
    def bytes(self)->int: return len(self.data)

def assemble_prompt(brief:dict,source_candidates:list[Candidate],profile:PromptProfile=BASELINE_PROFILE)->str:
    if profile.profile_id=="production-v2" and "editorial_idea" in brief:
        lines=["Rendering style:",profile.preamble,"","Exact source facts:"]
        for c in source_candidates:lines += [f"Title: {c.title}",f"Summary: {c.summary}"]
        lines += ["","Editorial idea:",brief["editorial_idea"],"","Central subject:",brief["central_subject"],"","Visual relationship:",brief["visual_relationship"],"","Composition:",brief["composition"],"","Permitted literal elements:",*brief["literal_elements"],"","Abstraction level:",brief["abstraction_level"],"","Story-specific forbidden elements:",*brief["forbidden_elements"],"","Likely failure modes to avoid:",*brief["failure_modes"],"","Global factual restrictions:","Do not fabricate visible factual evidence. Do not imitate a named or living artist. Do not render interfaces or screenshots.","Do not render any words, letters, numbers, labels, captions, annotations, signage, diagrams with text, logos, watermarks, or pseudo-writing anywhere in the image.","If the concept cannot be represented without visible text, represent the relationship through shape, scale, spacing, direction, grouping, interruption, containment, or contrast instead."]
    else:
        lines=[profile.preamble,"","Source stories (use only these facts):"]
        for c in source_candidates: lines += [f"Title: {c.title}",f"Summary: {c.summary}"]
        lines += ["",f"Central subject: {brief['central_subject']}",f"Visual metaphor: {brief['visual_metaphor']}",f"Composition: {brief['composition']}","Forbidden elements: "+(", ".join(brief["forbidden_elements"]) or "none beyond the fixed restrictions")]
    return "\n".join(lines).strip()+"\n"

def decode_image(value:str,provider_media_type:str|None=None)->tuple[bytes,str|None]:
    media=provider_media_type.lower() if provider_media_type else None; raw=value
    if value.startswith("data:"):
        m=re.fullmatch(r"data:([^;,]+);base64,(.+)",value,re.S)
        if not m: raise EditorialError("image_data_url_invalid")
        embedded=m.group(1).lower()
        if media and embedded!=media: raise EditorialError("image_media_type_mismatch")
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


def raster_media_type(data:bytes)->str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if data.startswith(b"\xff\xd8\xff"): return "image/jpeg"
    if len(data)>=12 and data[:4]==b"RIFF" and data[8:12]==b"WEBP": return "image/webp"
    raise EditorialError("image_raster_type_unsupported")


def normalize_raster(path:Path,declared_media_type:str|None,provider_max_bytes:int,max_pixels:int,final_max_bytes:int)->ValidatedImage:
    """Decode one provider raster and deterministically normalize it to opaque WebP."""
    try:data=path.read_bytes()
    except OSError as exc:raise EditorialError("image_provider_file_unreadable") from exc
    if not data:raise EditorialError("image_empty")
    if len(data)>provider_max_bytes:raise EditorialError("image_provider_too_large")
    magic=raster_media_type(data)
    if declared_media_type:
        declared=declared_media_type.lower().split(";",1)[0]
        if declared=="image/jpg":declared="image/jpeg"
        if declared not in ("image/png","image/jpeg","image/webp"):raise EditorialError("image_media_type_invalid")
        if declared!=magic:raise EditorialError("image_media_type_mismatch")
    try: from PIL import Image,ImageOps,UnidentifiedImageError
    except ImportError as exc: raise EditorialError("pillow_not_installed") from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error",Image.DecompressionBombWarning)
            with Image.open(path) as opened:
                if opened.format not in ("PNG","JPEG","WEBP"):raise EditorialError("image_raster_type_unsupported")
                expected={"PNG":"image/png","JPEG":"image/jpeg","WEBP":"image/webp"}[opened.format]
                if expected!=magic:raise EditorialError("image_media_type_mismatch")
                if getattr(opened,"n_frames",1)!=1 or getattr(opened,"is_animated",False):raise EditorialError("image_animated")
                width,height=opened.size
                if not (256<=width<=8192 and 256<=height<=8192):raise EditorialError("image_dimensions_unreasonable")
                if width*height>max_pixels:raise EditorialError("image_pixel_limit")
                if abs((width/height)-1.5)/1.5>0.08:raise EditorialError("image_aspect_ratio_invalid")
                opened.seek(0);opened.load();source=ImageOps.exif_transpose(opened)
                rgba=source.convert("RGBA")
                opaque=Image.new("RGB",rgba.size,(255,255,255));opaque.paste(rgba,mask=rgba.getchannel("A"))
                output=io.BytesIO()
                opaque.save(output,format="WEBP",quality=WEBP_QUALITY,method=WEBP_METHOD,lossless=False,exact=False,exif=b"",icc_profile=None,xmp=b"")
                final=output.getvalue()
    except EditorialError:raise
    except (Image.DecompressionBombError,Image.DecompressionBombWarning):raise EditorialError("image_decompression_bomb")
    except (UnidentifiedImageError,OSError,ValueError,TypeError) as exc:raise EditorialError("image_raster_malformed") from exc
    return validate_image(final,"image/webp",final_max_bytes)
