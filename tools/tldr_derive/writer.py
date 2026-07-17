"""Atomic writers and output path containment for derived artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Optional

from . import GENERATOR_VERSION, SCHEMA_VERSION
from .discovery import SourceIssue, derived_issue_relpath, is_tldr_sector_dir
from .models import IssueDocument, dumps_canonical, issue_to_canonical_json


class OutputContainmentError(ValueError):
    """Raised when a write would escape the configured output directory."""


def validate_output_root(repo_root: Path, output_root: Path) -> Path:
    """Reject output roots inside approved TLDR source directories.

    Must be called before any directory or file is created under ``output_root``.
    """
    root = repo_root.resolve()
    # Resolve without requiring the path to exist yet.
    out = output_root.expanduser()
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    else:
        out = out.resolve()

    try:
        rel = out.relative_to(root)
    except ValueError:
        # Output outside the repository is allowed.
        return out

    if rel.parts:
        first = rel.parts[0]
        if is_tldr_sector_dir(first):
            raise OutputContainmentError(
                f"refusing output root inside source newsletter directory: {out}"
            )
    return out


def ensure_within(output_root: Path, target: Path) -> Path:
    root = output_root.resolve()
    resolved = target.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise OutputContainmentError(
            f"refusing to write outside output root: {resolved} (root={root})"
        ) from exc
    return resolved


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def issue_output_path(output_root: Path, source: SourceIssue) -> Path:
    rel = derived_issue_relpath(source)
    return ensure_within(output_root, output_root / rel)


def write_issue(
    output_root: Path,
    source: SourceIssue,
    issue: IssueDocument,
    *,
    dry_run: bool = False,
) -> tuple[Path, str]:
    """Serialize and optionally write one issue. Returns (path, canonical_json)."""
    path = issue_output_path(output_root, source)
    payload = issue_to_canonical_json(issue)
    if not dry_run:
        atomic_write_text(path, payload)
    return path, payload


def build_manifest_entries(issues: list[IssueDocument]) -> list[dict[str, Any]]:
    entries = []
    for issue in issues:
        year = issue.date[:4]
        derived = f"issues/{issue.sector_slug}/{year}/{issue.date}.json"
        entries.append(
            {
                "issue_id": issue.issue_id,
                "sector": issue.sector,
                "sector_slug": issue.sector_slug,
                "date": issue.date,
                "source_path": issue.source_path,
                "source_content_hash": issue.source_content_hash,
                "schema_version": issue.schema_version,
                "generator_version": issue.generator_version,
                "format_family": issue.format_family,
                "parse_status": issue.parse_status,
                "derived_path": derived,
            }
        )
    entries.sort(key=lambda e: (e["sector_slug"], e["date"], e["issue_id"]))
    return entries


def write_manifest(
    output_root: Path,
    entries: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    merge_existing: bool = True,
) -> tuple[Path, str]:
    path = ensure_within(output_root, output_root / "manifest.json")
    merged = list(entries)
    if merge_existing and path.exists():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
            prior_entries = prior.get("issues", [])
            by_id = {e["issue_id"]: e for e in prior_entries}
            for entry in entries:
                by_id[entry["issue_id"]] = entry
            merged = sorted(
                by_id.values(),
                key=lambda e: (e["sector_slug"], e["date"], e["issue_id"]),
            )
        except (OSError, json.JSONDecodeError):
            merged = list(entries)

    doc = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "issues": merged,
    }
    payload = dumps_canonical(doc)
    if not dry_run:
        atomic_write_text(path, payload)
    return path, payload


def load_manifest_entries_by_source(output_root: Path) -> dict[str, dict[str, Any]]:
    """Map source_path -> manifest entry."""
    path = output_root / "manifest.json"
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for entry in doc.get("issues", []):
        src = entry.get("source_path")
        if src:
            result[src] = entry
    return result


def load_manifest_hashes(output_root: Path) -> dict[str, str]:
    """Map source_path -> source_content_hash from existing manifest."""
    return {
        src: entry["source_content_hash"]
        for src, entry in load_manifest_entries_by_source(output_root).items()
        if entry.get("source_content_hash")
    }


def filter_changed(
    sources: Iterable[SourceIssue],
    output_root: Path,
    *,
    schema_version: str = SCHEMA_VERSION,
    generator_version: str = GENERATOR_VERSION,
    manifest_entries: Optional[dict[str, dict[str, Any]]] = None,
) -> list[SourceIssue]:
    """Return sources that need regeneration (hash/missing/schema/generator)."""
    if manifest_entries is None:
        manifest_entries = load_manifest_entries_by_source(output_root)

    changed: list[SourceIssue] = []
    for source in sources:
        entry = manifest_entries.get(source.relative_path)
        derived = issue_output_path(output_root, source)
        if entry is None:
            changed.append(source)
            continue
        if entry.get("source_content_hash") != source.content_hash:
            changed.append(source)
            continue
        if not derived.exists():
            changed.append(source)
            continue
        if entry.get("schema_version") != schema_version:
            changed.append(source)
            continue
        if entry.get("generator_version") != generator_version:
            changed.append(source)
            continue
    return changed


def read_existing_issue_hash(output_root: Path, source: SourceIssue) -> Optional[str]:
    path = issue_output_path(output_root, source)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc.get("source_content_hash")
