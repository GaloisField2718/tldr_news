"""Cloudflare R2 storage abstraction backed by the maintained boto3 S3 client."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import quote,urlsplit
from .config import Config
from .core import EditorialError,validate_object_key

def build_public_url(config: Config, key: str) -> str:
    validate_object_key(key)
    base=config.r2_public_base_url
    p=urlsplit(base)
    if p.scheme!="https" or not p.netloc or p.query or p.fragment or p.username or p.password:
        raise EditorialError("r2_public_base_url_invalid")
    return base.rstrip("/")+"/"+"/".join(quote(x,safe="") for x in key.split("/"))

class R2Storage:
    def __init__(self,config:Config,client=None):
        self.config=config
        if client is None:
            try: import boto3
            except ImportError as exc: raise EditorialError("boto3_not_installed") from exc
            config.require_r2()
            client=boto3.client("s3",endpoint_url=config.r2_endpoint,region_name=config.r2_region,
                aws_access_key_id=config.r2_access_key_id,aws_secret_access_key=config.r2_secret_access_key)
        self.client=client
    def head_object(self,key:str):
        validate_object_key(key)
        try: return self.client.head_object(Bucket=self.config.r2_bucket,Key=key)
        except Exception as exc:
            code=str(getattr(exc,"response",{}).get("Error",{}).get("Code",""))
            if code in ("404","NoSuchKey","NotFound"): return None
            raise EditorialError("r2_head_failed") from exc
    def object_exists(self,key:str)->bool: return self.head_object(key) is not None
    def upload_object(self,path:Path,key:str,*,sha256:str,width:int,height:int,date:str)->None:
        validate_object_key(key,date)
        metadata={"sha256":sha256.removeprefix("sha256:"),"width":str(width),"height":str(height),"date":date,"generator-version":"1.0.0"}
        try: self.client.upload_file(str(path),self.config.r2_bucket,key,ExtraArgs={"ContentType":"image/webp","CacheControl":"public, max-age=31536000, immutable","Metadata":metadata})
        except Exception as exc: raise EditorialError("r2_upload_failed") from exc
    def verify_object(self,key:str,*,size:int,sha256:str)->dict:
        head=self.head_object(key)
        if head is None: raise EditorialError("r2_verification_missing")
        if head.get("ContentLength")!=size: raise EditorialError("r2_verification_size")
        if str(head.get("ContentType","")).split(";",1)[0].lower()!="image/webp": raise EditorialError("r2_verification_content_type")
        md=head.get("Metadata") or {}; stored=md.get("sha256")
        if stored is not None and stored.lower()!=sha256.removeprefix("sha256:").lower(): raise EditorialError("r2_verification_sha256")
        return head
    def ensure_uploaded(self,path:Path,key:str,*,size:int,sha256:str,width:int,height:int,date:str)->bool:
        if self.object_exists(key): self.verify_object(key,size=size,sha256=sha256); return False
        self.upload_object(path,key,sha256=sha256,width=width,height=height,date=date)
        self.verify_object(key,size=size,sha256=sha256); return True
    def build_public_url(self,key:str)->str:
        return build_public_url(self.config,key)
    def list_daily(self)->list[str]:
        keys=[]; token=None
        while True:
            args={"Bucket":self.config.r2_bucket,"Prefix":"daily/"}
            if token: args["ContinuationToken"]=token
            try: page=self.client.list_objects_v2(**args)
            except Exception as exc: raise EditorialError("r2_list_failed") from exc
            keys.extend(x["Key"] for x in page.get("Contents",[]) if isinstance(x,dict) and isinstance(x.get("Key"),str))
            if not page.get("IsTruncated"): break
            token=page.get("NextContinuationToken")
        return keys
