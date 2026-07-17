"""Discover TLDR newsletter Markdown sources on disk."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

FILENAME_RE = re.compile(r"^article_(\d{2})-(\d{2})-(\d{4})\.md$")


@dataclass(frozen=True)
class SourceIssue:
    path: Path
    relative_path: str
    sector: str
    sector_slug: str
    date_iso: str
    date_original: str
    content_hash: str
    size_bytes: int


class SourceContainmentError(ValueError):
    """Raised when a source path escapes the repository root."""


def is_tldr_sector_dir(name: str) -> bool:
    return name == "TLDR" or name.startswith("TLDR ")


def sector_slug(sector: str) -> str:
    slug = sector.strip().lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]+", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "unknown"


def parse_filename_date(filename: str) -> Optional[tuple[str, str]]:
    """Return (ISO YYYY-MM-DD, original DD-MM-YYYY) or None."""
    match = FILENAME_RE.match(filename)
    if not match:
        return None
    day, month, year = match.groups()
    original = f"{day}-{month}-{year}"
    try:
        parsed = date(int(year), int(month), int(day))
    except ValueError:
        return None
    return parsed.isoformat(), original


def content_sha256(data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    return f"sha256:{digest}"


def ensure_path_within_root(repo_root: Path, candidate: Path) -> Path:
    """Resolve candidate and require it to be inside repo_root via relative_to."""
    root = repo_root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SourceContainmentError(
            f"source path escapes repository root: {candidate}"
        ) from exc
    return resolved


def _source_from_resolved(root: Path, resolved: Path) -> SourceIssue:
    try:
        rel = resolved.relative_to(root)
    except ValueError as exc:
        raise SourceContainmentError(
            f"source path escapes repository root: {resolved}"
        ) from exc
    # Enforce the same direct top-level sector structure as discover_sources:
    # <sector>/<article_DD-MM-YYYY.md>
    if len(rel.parts) != 2:
        raise ValueError(
            f"source must be directly under a top-level TLDR sector directory: {rel}"
        )
    sector = rel.parts[0]
    if not is_tldr_sector_dir(sector):
        raise ValueError(f"source is not under an approved TLDR sector: {rel}")
    parsed = parse_filename_date(rel.parts[1])
    if parsed is None:
        raise ValueError(f"filename does not match article_DD-MM-YYYY.md: {rel}")
    if not resolved.is_file():
        raise FileNotFoundError(f"source not found: {rel}")
    date_iso, date_original = parsed
    raw = resolved.read_bytes()
    return SourceIssue(
        path=resolved,
        relative_path=str(rel).replace("\\", "/"),
        sector=sector,
        sector_slug=sector_slug(sector),
        date_iso=date_iso,
        date_original=date_original,
        content_hash=content_sha256(raw),
        size_bytes=len(raw),
    )


def discover_sources(repo_root: Path) -> list[SourceIssue]:
    """Find all approved TLDR issue Markdown files under repo_root."""
    root = repo_root.resolve()
    found: list[SourceIssue] = []
    for path in sorted(root.rglob("article_*.md")):
        if not path.is_file():
            continue
        try:
            resolved = ensure_path_within_root(root, path)
            found.append(_source_from_resolved(root, resolved))
        except (SourceContainmentError, ValueError, FileNotFoundError):
            continue
    found.sort(key=lambda s: (s.sector_slug, s.date_iso, s.relative_path))
    return found


def resolve_source(repo_root: Path, source: str) -> SourceIssue:
    """Resolve a single --source path argument to a SourceIssue."""
    root = repo_root.resolve()
    candidate = Path(source)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = ensure_path_within_root(root, candidate)
    return _source_from_resolved(root, resolved)


def issue_id_for(source: SourceIssue) -> str:
    return f"{source.sector_slug}:{source.date_iso}"


def derived_issue_relpath(source: SourceIssue) -> str:
    year = source.date_iso[:4]
    return f"issues/{source.sector_slug}/{year}/{source.date_iso}.json"
