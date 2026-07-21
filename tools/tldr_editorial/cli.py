from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from .artifacts import validate_all
from .config import Config
from .core import EditorialError
from .generator import generate
from .r2_storage import R2Storage

def parser():
    p=argparse.ArgumentParser(prog="python3 -m tools.tldr_editorial")
    sub=p.add_subparsers(dest="command",required=True)
    g=sub.add_parser("generate"); sel=g.add_mutually_exclusive_group(); sel.add_argument("--date"); sel.add_argument("--latest",action="store_true")
    g.add_argument("--output",type=Path,default=Path("generated/editorial")); g.add_argument("--generated",type=Path,default=Path("generated"))
    for x in ("force","retry-image","dry-run","offline","require-live"): g.add_argument("--"+x,action="store_true")
    v=sub.add_parser("validate"); v.add_argument("--all",action="store_true",required=True); v.add_argument("--output",type=Path,default=Path("generated/editorial")); v.add_argument("--generated",type=Path,default=Path("generated")); v.add_argument("--verify-storage",action="store_true")
    s=sub.add_parser("storage-report"); s.add_argument("--output",type=Path,default=Path("generated/editorial")); s.add_argument("--list-r2",action="store_true")
    return p

def main(argv=None):
    a=parser().parse_args(argv)
    try:
        if a.command=="generate":
            result=generate(generated=a.generated,output=a.output,date=a.date,latest=a.latest or not a.date,offline=a.offline,dry_run=a.dry_run,require_live=a.require_live,force=a.force,retry_image=a.retry_image)
            print(json.dumps(result,sort_keys=True)); return 0
        if a.command=="validate":
            cfg=Config.from_env(); storage=R2Storage(cfg) if a.verify_storage else None
            errors=validate_all(a.output,a.generated,storage,cfg.r2_public_base_url,cfg.max_candidates,cfg.editorial_model,cfg.image_model,cfg.max_provider_image_bytes,cfg.max_image_pixels,cfg.max_image_bytes)
            if errors:
                for e in errors: print(e,file=sys.stderr)
                return 1
            print(json.dumps({"valid":True,"output":str(a.output),"live_storage_verified":a.verify_storage},sort_keys=True)); return 0
        refs=set(); m=a.output/"manifest.json"
        if m.exists():
            for x in json.loads(m.read_text(encoding="utf-8")).get("dates",[]):
                if x.get("illustration_object_key"): refs.add(x["illustration_object_key"])
        result={"referenced":sorted(refs),"r2_listed":False,"potentially_unreferenced":[]}
        if a.list_r2:
            keys=set(R2Storage(Config.from_env()).list_daily()); result.update(r2_listed=True,potentially_unreferenced=sorted(keys-refs))
        print(json.dumps(result,sort_keys=True)); return 0
    except EditorialError as exc:
        print(f"editorial_error: {exc}",file=sys.stderr); return 2
