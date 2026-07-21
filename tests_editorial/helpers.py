from __future__ import annotations
import json,struct
from pathlib import Path
from tools.tldr_editorial.config import Config

def config(**changes):
    base=dict(enabled=False,api_key="",editorial_model="openai/gpt-5.6-luna",image_model="google/gemini-3.1-flash-lite-image",http_referer="",app_title="TLDR Daily Index",max_candidates=60,max_image_bytes=2_000_000,max_provider_image_bytes=12_000_000,max_image_pixels=20_000_000,editorial_timeout=90,image_timeout=180,max_attempts=1,r2_account_id="acct",r2_access_key_id="id",r2_secret_access_key="secret",r2_bucket="bucket",r2_public_base_url="https://assets.example.workers.dev",r2_endpoint="https://acct.r2.cloudflarestorage.com",r2_region="auto")
    base.update(changes); return Config(**base)

def article(aid,title="Title",summary="Summary",url=None,content_type="editorial",sponsor=False,order=1):
    return {"id":aid,"order":order,"title":title,"summary":summary,"url":url or f"https://example.com/{aid}","source_domain":"example.com","reading_time_minutes":3,"content_type":content_type,"is_sponsor":sponsor}

def write_generated(root:Path,date="2026-07-21",sectors=None):
    sectors=sectors or {"tldr":[article("tldr:"+date+":a01"),article("tldr:"+date+":a02",title="Second")],"tldr-ai":[article("tldr-ai:"+date+":a01",title="AI story")]}
    entries=[]
    for slug,articles in sectors.items():
        issue_id=f"{slug}:{date}"; rel=f"issues/{slug}/{date[:4]}/{date}.json"; p=root/rel;p.parent.mkdir(parents=True,exist_ok=True)
        issue={"schema_version":"1.0.0","generator_version":"0.1.3","issue_id":issue_id,"sector":slug,"sector_slug":slug,"date":date,"source_path":"x.md","parse_status":"complete","sections":[{"id":"s","heading":"NEWS","order":1,"articles":articles}]}
        p.write_text(json.dumps(issue),encoding="utf-8")
        entries.append({"issue_id":issue_id,"sector":slug,"sector_slug":slug,"date":date,"source_path":"x.md","source_content_hash":"sha256:x","schema_version":"1.0.0","generator_version":"0.1.3","format_family":"x","parse_status":"complete","derived_path":rel})
    root.mkdir(parents=True,exist_ok=True);(root/"manifest.json").write_text(json.dumps({"schema_version":"1.0.0","generator_version":"0.1.3","issues":entries}),encoding="utf-8")

def fake_webp(width=600,height=400):
    payload=b"\x00"*10
    chunk=b"VP8X"+struct.pack("<I",10)+b"\x00\x00\x00\x00"+(width-1).to_bytes(3,"little")+(height-1).to_bytes(3,"little")
    data=b"RIFF"+struct.pack("<I",4+len(chunk))+b"WEBP"+chunk
    return data
