"""Structural consistency checks for generated/ derived-data artifacts.

Stdlib only. Used by push_script.sh before commit. Not part of the parser.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.tldr_derive import GENERATOR_VERSION, SCHEMA_VERSION


def check_generated(output_root: Path) -> list[str]:
    """Return a list of human-readable problems (empty means OK)."""
    errors: list[str] = []
    manifest_path = output_root / "manifest.json"
    issues_root = output_root / "issues"

    if not manifest_path.is_file():
        return [f"missing manifest: {manifest_path}"]

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"manifest.json is not valid JSON: {exc}"]

    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]

    entries = manifest.get("issues")
    if not isinstance(entries, list):
        return ["manifest.json missing issues list"]

    if manifest.get("generator_version") != GENERATOR_VERSION:
        errors.append(
            "manifest generator_version mismatch: "
            f"{manifest.get('generator_version')!r} != {GENERATOR_VERSION!r}"
        )
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            "manifest schema_version mismatch: "
            f"{manifest.get('schema_version')!r} != {SCHEMA_VERSION!r}"
        )

    issue_ids: set[str] = set()
    source_paths: set[str] = set()
    derived_paths: set[str] = set()

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"manifest issues[{idx}] is not an object")
            continue
        issue_id = entry.get("issue_id") or entry.get("id")
        source_path = entry.get("source_path")
        derived = entry.get("derived_path")
        if not issue_id:
            errors.append(f"manifest issues[{idx}] missing issue_id")
        else:
            if issue_id in issue_ids:
                errors.append(f"duplicate manifest issue_id: {issue_id}")
            issue_ids.add(str(issue_id))
        if not source_path:
            errors.append(f"manifest issues[{idx}] missing source_path")
        else:
            if source_path in source_paths:
                errors.append(f"duplicate manifest source_path: {source_path}")
            source_paths.add(str(source_path))
            if "GoDaddy" in str(source_path):
                errors.append(f"GoDaddy path in manifest: {source_path}")
        if not derived:
            errors.append(f"manifest issues[{idx}] missing derived_path")
        else:
            if derived in derived_paths:
                errors.append(f"duplicate manifest derived_path: {derived}")
            derived_paths.add(str(derived))
            derived_file = output_root / str(derived)
            if not derived_file.is_file():
                errors.append(f"missing derived file for {derived}")

    issue_files = sorted(issues_root.rglob("*.json")) if issues_root.is_dir() else []
    if any("godaddy" in str(p).lower() for p in issue_files):
        errors.append("GoDaddy output exists under generated/issues")

    if len(issue_files) != len(entries):
        errors.append(
            f"issue file count ({len(issue_files)}) != manifest entries ({len(entries)})"
        )

    for path in issue_files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid issue JSON {path}: {exc}")
            continue
        if not isinstance(doc, dict):
            errors.append(f"issue root not object: {path}")
            continue
        if doc.get("generator_version") != GENERATOR_VERSION:
            errors.append(
                f"{path}: generator_version {doc.get('generator_version')!r} "
                f"!= {GENERATOR_VERSION!r}"
            )
        if doc.get("schema_version") != SCHEMA_VERSION:
            errors.append(
                f"{path}: schema_version {doc.get('schema_version')!r} "
                f"!= {SCHEMA_VERSION!r}"
            )
        if "godaddy" in str(path).lower() or "GoDaddy" in str(doc.get("source_path", "")):
            errors.append(f"GoDaddy issue output: {path}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="generated",
        help="Derived-data output root (default: generated)",
    )
    args = parser.parse_args(argv)
    output_root = Path(args.output)
    errors = check_generated(output_root)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        print(f"consistency_check_failed count={len(errors)}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "output": str(output_root)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
