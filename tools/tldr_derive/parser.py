"""Orchestrate format detection and parsing into IssueDocument."""

from __future__ import annotations

from .discovery import SourceIssue, issue_id_for
from .models import IssueDocument, WarningRecord
from .parser_common import clean_text, detect_format_family, extract_issue_title
from .parser_inline import parse_inline_url
from .parser_references import parse_links_block


_MATERIAL_WARNING_CODES = {
    "dangling_reference",
    "missing_reference_number",
    "missing_inline_url",
    "missing_links_block",
    "unknown_format",
    "empty_body",
}


def _count_editorial_articles(sections) -> int:
    return sum(
        1
        for section in sections
        for article in section.articles
        if not article.is_sponsor
    )


def _count_all_articles(sections) -> int:
    return sum(len(section.articles) for section in sections)


def _sort_warnings(warnings: list[WarningRecord]) -> list[WarningRecord]:
    return sorted(
        warnings,
        key=lambda w: (
            w.code,
            w.line if w.line is not None else -1,
            w.message,
        ),
    )


def decide_status(
    sections,
    warnings: list[WarningRecord],
    text: str,
) -> str:
    article_count = _count_all_articles(sections)
    body = text.strip()
    lines = [ln for ln in body.splitlines() if ln.strip()]
    header_only = len(lines) <= 2 and (not lines or lines[0].startswith("#"))

    if article_count == 0:
        return "failed"

    material = [w for w in warnings if w.code in _MATERIAL_WARNING_CODES]
    # Unresolved editorial URLs are material.
    unresolved_editorial = any(
        (article.url is None and not article.is_sponsor)
        for section in sections
        for article in section.articles
    )
    if material or unresolved_editorial:
        return "partial"
    if header_only:
        return "failed"
    return "complete"


def parse_source(source: SourceIssue, raw_text: str) -> IssueDocument:
    text = clean_text(raw_text)
    issue_id = issue_id_for(source)
    format_family = detect_format_family(text)
    warnings: list[WarningRecord] = []

    if format_family == "links_block":
        sections, parse_warnings = parse_links_block(text, issue_id)
        warnings.extend(parse_warnings)
    elif format_family == "inline_url":
        sections, parse_warnings = parse_inline_url(text, issue_id)
        warnings.extend(parse_warnings)
    else:
        warnings.append(
            WarningRecord(
                code="unknown_format",
                message="Could not detect links_block or inline_url format",
                line=None,
            )
        )
        # Best-effort: try links_block then inline.
        sections, w1 = parse_links_block(text, issue_id)
        if _count_all_articles(sections) == 0:
            sections, w2 = parse_inline_url(text, issue_id)
            warnings.extend(w2)
        else:
            warnings.extend(w1)

    if not text.strip():
        warnings.append(
            WarningRecord(code="empty_body", message="Source file is empty", line=None)
        )

    warnings = _sort_warnings(warnings)
    status = decide_status(sections, warnings, text)
    title = extract_issue_title(source.sector, source.date_iso, text)

    # Stable section/article ordering already assigned 1-based during parse.
    # Ensure section ids unique by suffixing duplicates.
    seen: dict[str, int] = {}
    for section in sections:
        base = section.id
        count = seen.get(base, 0)
        seen[base] = count + 1
        if count:
            section.id = f"{base}-{count + 1}"

    return IssueDocument(
        issue_id=issue_id,
        sector=source.sector,
        sector_slug=source.sector_slug,
        date=source.date_iso,
        source_path=source.relative_path,
        source_content_hash=source.content_hash,
        format_family=format_family,
        parse_status=status,
        parse_warnings=warnings,
        title=title,
        sections=sections,
    )
