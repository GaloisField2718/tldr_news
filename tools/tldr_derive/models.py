"""Data models and serialization helpers for derived TLDR issues.

Ordering convention
-------------------
``sections[].order`` and ``articles[].order`` are **1-based** integers.
The first section and first article in document order both receive ``order: 1``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from . import GENERATOR_VERSION, SCHEMA_VERSION


@dataclass(frozen=True)
class WarningRecord:
    code: str
    message: str
    line: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "line": self.line,
        }


@dataclass
class Article:
    id: str
    order: int
    title: str
    summary: str
    url: Optional[str]
    reading_time_minutes: Optional[int]
    source_domain: Optional[str]
    content_type: str
    is_sponsor: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "order": self.order,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "reading_time_minutes": self.reading_time_minutes,
            "source_domain": self.source_domain,
            "content_type": self.content_type,
            "is_sponsor": self.is_sponsor,
        }


@dataclass
class Section:
    id: str
    heading: str
    order: int
    articles: list[Article] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "heading": self.heading,
            "order": self.order,
            "articles": [a.to_dict() for a in self.articles],
        }


@dataclass
class IssueDocument:
    issue_id: str
    sector: str
    sector_slug: str
    date: str
    source_path: str
    source_content_hash: str
    format_family: str
    parse_status: str
    parse_warnings: list[WarningRecord]
    title: str
    sections: list[Section]
    schema_version: str = SCHEMA_VERSION
    generator_version: str = GENERATOR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generator_version": self.generator_version,
            "issue_id": self.issue_id,
            "sector": self.sector,
            "sector_slug": self.sector_slug,
            "date": self.date,
            "source_path": self.source_path,
            "source_content_hash": self.source_content_hash,
            "format_family": self.format_family,
            "parse_status": self.parse_status,
            "parse_warnings": [w.to_dict() for w in self.parse_warnings],
            "title": self.title,
            "sections": [s.to_dict() for s in self.sections],
        }


def dumps_canonical(obj: Any) -> str:
    """Serialize to deterministic UTF-8 JSON with a trailing newline."""
    return (
        json.dumps(
            obj,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
            separators=(",", ": "),
        )
        + "\n"
    )


def issue_to_canonical_json(issue: IssueDocument) -> str:
    return dumps_canonical(issue.to_dict())
