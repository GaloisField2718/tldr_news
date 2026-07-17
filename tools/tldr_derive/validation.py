"""Validation helpers for derived outputs and sources (read-only)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .discovery import SourceIssue, discover_sources
from .parser import parse_source
from .sanitizer import is_private_url


@dataclass
class ValidationReport:
    """Corpus validation summary.

    ``processed_count`` is the number of sources parsed without raising an
    exception. It is **not** the count of ``parse_status == "complete"`` issues.
    Use ``parse_status_counts`` for complete/partial/failed totals.
    """

    source_count: int = 0
    processed_count: int = 0
    error_count: int = 0
    parse_status_counts: dict[str, int] = field(default_factory=dict)
    format_family_counts: dict[str, int] = field(default_factory=dict)
    warning_code_counts: dict[str, int] = field(default_factory=dict)
    privacy_hits: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings_sample: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_count": self.source_count,
            # processed_count: parsed without exception (not parse_status=complete).
            "processed_count": self.processed_count,
            "error_count": self.error_count,
            "parse_status_counts": dict(sorted(self.parse_status_counts.items())),
            "format_family_counts": dict(sorted(self.format_family_counts.items())),
            "warning_code_counts": dict(sorted(self.warning_code_counts.items())),
            "privacy_hits": self.privacy_hits,
            "errors": self.errors,
            "warnings_sample": self.warnings_sample,
        }


def _scan_issue_privacy(issue_dict: dict[str, Any], source_path: str) -> list[str]:
    hits: list[str] = []
    for section in issue_dict.get("sections", []):
        for article in section.get("articles", []):
            url = article.get("url")
            if not url:
                continue
            if is_private_url(url):
                hits.append(f"{source_path}: private url slipped through")
                continue
            if re.search(r"[?&](email|subscriber|subscriber_id)=", url, re.IGNORECASE):
                hits.append(f"{source_path}: subscriber parameter in article url")
            # Flag only TLDR management hosts with manage/unsubscribe paths.
            if re.search(
                r"https?://(?:[\w.-]+\.)?(?:tldr\.tech|tldrnewsletter\.com)/[^\s]*"
                r"(?:/manage(?:/|\?)|/unsubscribe(?:/|\?)|unsubscribe\?)",
                url,
                re.IGNORECASE,
            ):
                hits.append(f"{source_path}: TLDR management url in article url")
            if re.search(r"hub\.sparklp\.co|refer\.tldr\.tech", url, re.IGNORECASE):
                hits.append(f"{source_path}: referral/account url in article url")
    return hits


def validate_sources(
    repo_root: Path,
    sources: Optional[list[SourceIssue]] = None,
) -> ValidationReport:
    """Parse all sources in memory; never writes."""
    report = ValidationReport()
    if sources is None:
        sources = discover_sources(repo_root)
    report.source_count = len(sources)

    for source in sources:
        try:
            text = source.path.read_text(encoding="utf-8")
            issue = parse_source(source, text)
            report.processed_count += 1
            report.parse_status_counts[issue.parse_status] = (
                report.parse_status_counts.get(issue.parse_status, 0) + 1
            )
            report.format_family_counts[issue.format_family] = (
                report.format_family_counts.get(issue.format_family, 0) + 1
            )
            for warning in issue.parse_warnings:
                report.warning_code_counts[warning.code] = (
                    report.warning_code_counts.get(warning.code, 0) + 1
                )
            issue_dict = issue.to_dict()
            privacy = _scan_issue_privacy(issue_dict, source.relative_path)
            report.privacy_hits.extend(privacy)
            if issue.parse_warnings and len(report.warnings_sample) < 50:
                report.warnings_sample.append(
                    {
                        "source_path": source.relative_path,
                        "parse_status": issue.parse_status,
                        "warnings": [w.to_dict() for w in issue.parse_warnings[:5]],
                    }
                )
        except Exception as exc:  # noqa: BLE001 - isolate per-file failures
            report.error_count += 1
            report.errors.append(
                {
                    "source_path": source.relative_path,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )
    return report
