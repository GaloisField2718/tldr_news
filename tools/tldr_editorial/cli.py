from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from .artifacts import validate_all
from .calibration import calibrate_images,parse_combinations
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
    c=sub.add_parser("calibrate-images");c.add_argument("--date",required=True);styles=c.add_mutually_exclusive_group();styles.add_argument("--style-profiles");styles.add_argument("--profiles");c.add_argument("--concepts");c.add_argument("--combinations");c.add_argument("--output-dir",type=Path,required=True);c.add_argument("--max-images",type=int,required=True);samples=c.add_mutually_exclusive_group();samples.add_argument("--samples-per-combination",type=int);samples.add_argument("--samples-per-profile",type=int);c.add_argument("--require-live",action="store_true");c.add_argument("--acknowledge-cost",action="store_true")
    return p

def main(argv=None):
    a=parser().parse_args(argv)
    try:
        if a.command=="generate":
            result=generate(generated=a.generated,output=a.output,date=a.date,latest=a.latest or not a.date,offline=a.offline,dry_run=a.dry_run,require_live=a.require_live,force=a.force,retry_image=a.retry_image)
            print(json.dumps(result,sort_keys=True)); return 0
        if a.command=="calibrate-images":
            style_value=a.style_profiles or a.profiles
            if a.combinations is not None and (style_value is not None or a.concepts is not None):raise EditorialError("calibration_combination_mode_conflict")
            if a.profiles is not None and a.concepts is not None:raise EditorialError("calibration_legacy_profiles_concepts_conflict")
            ids=[x.strip() for x in style_value.split(",") if x.strip()] if style_value is not None else None;concept_ids=[x.strip() for x in a.concepts.split(",") if x.strip()] if a.concepts is not None else None;combinations=parse_combinations(a.combinations) if a.combinations is not None else None
            result=calibrate_images(date=a.date,profile_ids=ids,concept_ids=concept_ids,combinations=combinations,output_dir=a.output_dir,max_images=a.max_images,samples_per_combination=a.samples_per_combination if a.samples_per_combination is not None else 1,samples_per_profile=a.samples_per_profile,require_live=a.require_live,acknowledge_cost=a.acknowledge_cost)
            print(json.dumps(result,sort_keys=True));return 0 if result["success"] else 1
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
