"""Parser for modern TLDR issues that use a numbered Links: block."""

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

_REF_AT_END_RE = re.compile(r"\[(\d+)\]\s*$")
_LINK_DEF_RE = re.compile(r"^\[(\d+)\]\s+(\S+)\s*$")
_TITLE_HINT_RE = re.compile(
    r"(MINUTE\s+READ|\(SPONSOR\)|\(GITHUB|\(COURSE\)|\(TOOL\)|\(APP\)|\(WEBSITE\))",
    re.IGNORECASE,
)


def parse_link_definitions(links_text: str) -> dict[int, str]:
    defs: dict[int, str] = {}
    pending_num: Optional[int] = None
    pending_parts: list[str] = []
    for line in links_text.splitlines():
        stripped = line.strip()
        if not stripped or set(stripped) <= {"-"}:
            continue
        match = _LINK_DEF_RE.match(stripped)
        if match:
            if pending_num is not None and pending_parts:
                defs[pending_num] = "".join(pending_parts)
            pending_num = int(match.group(1))
            pending_parts = [match.group(2)]
            continue
        if pending_num is not None:
            pending_parts.append(stripped)
    if pending_num is not None and pending_parts:
        defs[pending_num] = "".join(pending_parts)
    return defs


def _looks_like_title_start(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if is_section_heading(stripped) or is_emoji_only_line(stripped):
        return False
    if stripped.startswith("#"):
        return False
    lower = stripped.lower()
    if lower.startswith("sign up"):
        return False
    if lower.startswith("advertise"):
        return False
    if lower.startswith("view online"):
        return False
    if lower.startswith("together with"):
        # Sponsor intro line; allow as title start only with markers later.
        pass
    if re.match(r"^TLDR\b", stripped, re.IGNORECASE):
        return False
    if re.match(r"^DAILY\b", stripped, re.IGNORECASE):
        return False
    if _REF_AT_END_RE.search(stripped):
        return True
    if _TITLE_HINT_RE.search(stripped):
        return True
    letters = re.sub(r"[^A-Za-z]", "", stripped)
    if letters and letters.upper() == letters and len(stripped) >= 12:
        return True
    return False


def parse_links_block(
    text: str,
    issue_id: str,
) -> tuple[list[Section], list[WarningRecord]]:
    warnings: list[WarningRecord] = []

    if "Links:" in text:
        body, _, links = text.partition("Links:")
        link_defs = parse_link_definitions(links)
    else:
        body = text
        link_defs = {}
        warnings.append(
            WarningRecord(
                code="missing_links_block",
                message="Expected Links: block for links_block format",
                line=None,
            )
        )

    body, footer_removed = truncate_footer(body)
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
        articles: list[Article] = []
        for idx, raw in enumerate(pending, start=1):
            articles.append(
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
            )
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
        while j < len(lines) and not _REF_AT_END_RE.search(title_parts[-1]):
            nxt = lines[j].strip()
            if not nxt:
                break
            if is_section_heading(nxt) or is_emoji_only_line(nxt):
                break
            # Continuation may itself look like a title start (wrapped headline).
            title_parts.append(nxt)
            j += 1
            if _REF_AT_END_RE.search(nxt):
                break
            if j - i > 6:
                break

        title_joined = " ".join(title_parts)
        ref_match = _REF_AT_END_RE.search(title_joined)
        ref_num: Optional[int] = int(ref_match.group(1)) if ref_match else None
        if ref_match:
            title_joined = title_joined[: ref_match.start()].rstrip()

        reading_time = extract_reading_time(title_joined)
        content_type, is_sponsor = classify_content(title_joined)
        title = strip_markers_from_title(title_joined)

        summary_parts: list[str] = []
        k = j
        if k < len(lines) and not lines[k].strip():
            k += 1
        while k < len(lines):
            nxt = lines[k].strip()
            if not nxt:
                break
            if is_section_heading(nxt) or is_emoji_only_line(nxt):
                break
            if _looks_like_title_start(nxt):
                break
            summary_parts.append(nxt)
            k += 1

        summary = " ".join(summary_parts).strip()
        article_seq += 1
        article_id = (
            f"{issue_id}:a{ref_num:02d}"
            if ref_num is not None
            else f"{issue_id}:o{article_seq:03d}"
        )

        url = None
        domain = None
        src_line = line_offset + i + 1
        skip_article = False
        if ref_num is None:
            # Require a content marker for ref-less titles.
            if not _TITLE_HINT_RE.search(title_joined):
                i = k
                continue
            warnings.append(
                WarningRecord(
                    code="missing_reference_number",
                    message=f"Article '{title}' has no reference number",
                    line=src_line,
                )
            )
        elif ref_num not in link_defs:
            warnings.append(
                WarningRecord(
                    code="dangling_reference",
                    message=f"Reference {ref_num} has no link definition",
                    line=src_line,
                )
            )
        else:
            url = normalize_public_url(link_defs[ref_num])
            if url is None:
                # Private/nav/account links are omitted from editorial output.
                warnings.append(
                    WarningRecord(
                        code="skipped_private_or_invalid_url",
                        message=(
                            f"Reference {ref_num} omitted after privacy/"
                            "validity sanitization"
                        ),
                        line=src_line,
                    )
                )
                skip_article = True
            else:
                domain = source_domain_from_url(url)

        if skip_article:
            i = k
            continue

        pending.append(
            {
                "id": article_id,
                "title": title,
                "summary": summary,
                "url": url,
                "reading_time_minutes": reading_time,
                "source_domain": domain,
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
