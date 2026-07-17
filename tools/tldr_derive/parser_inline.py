"""Parser for historical TLDR issues with inline [https://...] links."""

from __future__ import annotations

import re
from typing import Any, Optional

from .models import Article, Section, WarningRecord
from .parser_common import (
    classify_content,
    extract_reading_time,
    is_emoji_only_line,
    is_section_heading,
    normalize_section_heading,
    skip_preamble,
    slugify_heading,
    strip_markers_from_title,
)
from .sanitizer import normalize_public_url, source_domain_from_url, truncate_footer

_INLINE_URL_RE = re.compile(r"^\[(https?://.+)\]\s*$")
_TITLE_HINT_RE = re.compile(
    r"(MINUTE\s+READ|\(SPONSOR\)|\(GITHUB|\(COURSE\)|\(TOOL\)|\(APP\)|\(WEBSITE\))",
    re.IGNORECASE,
)


def _looks_like_title_start(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if is_section_heading(stripped) or is_emoji_only_line(stripped):
        return False
    if stripped.startswith("#") or stripped.startswith("["):
        return False
    if stripped.lower().startswith("sign up"):
        return False
    if re.match(r"^TLDR\b", stripped, re.IGNORECASE):
        return False
    if re.match(r"^DAILY\b", stripped, re.IGNORECASE):
        return False
    if _TITLE_HINT_RE.search(stripped):
        return True
    letters = re.sub(r"[^A-Za-z]", "", stripped)
    if letters and letters.upper() == letters and len(stripped) >= 12:
        return True
    return False


def _consume_inline_url(lines: list[str], start: int) -> tuple[Optional[str], int]:
    """Read a possibly wrapped [https://...] URL starting at start."""
    if start >= len(lines):
        return None, start
    stripped = lines[start].strip()
    if not stripped.startswith("[http"):
        return None, start
    parts = [stripped]
    j = start + 1
    while j < len(lines) and "]" not in parts[-1]:
        nxt = lines[j].strip()
        if not nxt:
            break
        parts.append(nxt)
        j += 1
        if "]" in nxt:
            break
        if j - start > 8:
            break
    joined = "".join(p.strip() for p in parts)
    match = re.match(r"^\[(https?://.+)\]\s*$", joined)
    if not match:
        # Soft-fail: still try to extract URL-looking content.
        inner = joined.strip("[]")
        if inner.startswith("http"):
            return inner, j
        return None, start + 1
    return match.group(1), j


def parse_inline_url(
    text: str,
    issue_id: str,
) -> tuple[list[Section], list[WarningRecord]]:
    warnings: list[WarningRecord] = []
    body, footer_removed = truncate_footer(text)
    if footer_removed:
        warnings.append(
            WarningRecord(
                code="footer_truncated",
                message="Subscription/account footer truncated before parse",
                line=None,
            )
        )

    lines = body.splitlines()
    start = skip_preamble(lines)
    lines = lines[start:]
    line_offset = start

    sections: list[Section] = []
    current_heading = "GENERAL"
    pending: list[dict[str, Any]] = []
    section_order = 0

    def flush_section() -> None:
        nonlocal section_order, pending, current_heading
        if not pending and current_heading == "GENERAL" and not sections:
            return
        section_order += 1
        articles = [
            Article(
                id=raw["id"],
                order=idx,
                title=raw["title"],
                summary=raw["summary"],
                url=raw["url"],
                reading_time_minutes=raw["reading_time_minutes"],
                source_domain=raw["source_domain"],
                content_type=raw["content_type"],
                is_sponsor=raw["is_sponsor"],
            )
            for idx, raw in enumerate(pending, start=1)
        ]
        sections.append(
            Section(
                id=slugify_heading(current_heading),
                heading=current_heading,
                order=section_order,
                articles=articles,
            )
        )
        pending = []

    i = 0
    article_seq = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if is_emoji_only_line(stripped):
            i += 1
            continue
        if is_section_heading(stripped):
            flush_section()
            current_heading = normalize_section_heading(stripped)
            i += 1
            continue

        if not _looks_like_title_start(stripped):
            i += 1
            continue

        title_parts = [stripped]
        j = i + 1
        while j < len(lines):
            nxt = lines[j].strip()
            if not nxt:
                break
            if nxt.startswith("[http"):
                break
            if is_section_heading(nxt) or is_emoji_only_line(nxt):
                break
            if _looks_like_title_start(nxt) and _TITLE_HINT_RE.search(nxt):
                break
            # Continue title wrap until marker complete or URL.
            if _TITLE_HINT_RE.search(" ".join(title_parts)) and not _TITLE_HINT_RE.search(
                nxt
            ):
                # Likely finished title markers; stop unless clearly continuation.
                if nxt.isupper() or len(nxt) < 40:
                    title_parts.append(nxt)
                    j += 1
                    continue
                break
            title_parts.append(nxt)
            j += 1
            if j - i > 6:
                break

        title_joined = " ".join(title_parts)
        reading_time = extract_reading_time(title_joined)
        content_type, is_sponsor = classify_content(title_joined)
        title = strip_markers_from_title(title_joined)

        url_raw, after_url = _consume_inline_url(lines, j)
        src_line = line_offset + i + 1

        # Require a recognizable article marker for inline-era titles.
        if not _TITLE_HINT_RE.search(title_joined):
            i = j
            continue

        url = normalize_public_url(url_raw) if url_raw else None
        if url_raw and url is None:
            warnings.append(
                WarningRecord(
                    code="skipped_private_or_invalid_url",
                    message="Inline URL omitted after privacy/validity sanitization",
                    line=src_line,
                )
            )
            i = after_url
            continue
        if url_raw is None:
            warnings.append(
                WarningRecord(
                    code="missing_inline_url",
                    message=f"Article '{title}' has no inline URL",
                    line=src_line,
                )
            )

        k = after_url if url_raw is not None else j
        if k < len(lines) and not lines[k].strip():
            k += 1

        summary_parts: list[str] = []
        while k < len(lines):
            nxt = lines[k].strip()
            if not nxt:
                break
            if is_section_heading(nxt) or is_emoji_only_line(nxt):
                break
            if nxt.startswith("[http"):
                break
            if _looks_like_title_start(nxt):
                break
            summary_parts.append(nxt)
            k += 1

        article_seq += 1
        pending.append(
            {
                "id": f"{issue_id}:o{article_seq:03d}",
                "title": title,
                "summary": " ".join(summary_parts).strip(),
                "url": url,
                "reading_time_minutes": reading_time,
                "source_domain": source_domain_from_url(url),
                "content_type": content_type,
                "is_sponsor": is_sponsor,
            }
        )
        i = k

    flush_section()

    if len(sections) > 1:
        sections = [
            s for s in sections if not (s.heading == "GENERAL" and not s.articles)
        ]
        for idx, section in enumerate(sections, start=1):
            section.order = idx

    return sections, warnings
