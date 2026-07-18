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
# Trailing editorial inline URL on a title line (possibly after markers).
_TRAILING_BRACKET_URL_START_RE = re.compile(r"\[(https?://)", re.IGNORECASE)
# Second line of a wrapped "(N MINUTE READ)" marker.
_READING_TIME_CONTINUATION_RE = re.compile(
    r"^MINUTE(?:S)?\s+READ\)\s*$",
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


def _consume_bracket_url_fragment(
    lines: list[str],
    start: int,
    first_fragment: str,
) -> tuple[Optional[str], int]:
    """
    Consume a bracketed URL that begins at first_fragment (must start with
    '[http') and may continue across subsequent lines until ']'.
    """
    parts = [first_fragment.strip()]
    j = start + 1
    while "]" not in "".join(parts) and j < len(lines):
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
    if match:
        return match.group(1), j
    inner = joined.strip("[]")
    if inner.startswith("http"):
        return inner, j
    return None, start + 1


def _split_trailing_inline_url(
    line: str,
) -> tuple[str, Optional[str], Optional[str]]:
    """
    If line contains a trailing [https://...] (complete or open), return
    (title_prefix, complete_url_or_none, open_fragment_or_none).

    open_fragment is set when '[' starts an http URL but ']' is missing so
    the caller can continue on following lines.
    """
    match = _TRAILING_BRACKET_URL_START_RE.search(line)
    if not match:
        return line, None, None
    idx = match.start()
    prefix = line[:idx].rstrip()
    rest = line[idx:]
    if "]" in rest:
        close = rest.find("]")
        inner = rest[1:close]
        if inner.lower().startswith("http"):
            return prefix, inner, None
        return line, None, None
    if rest.lower().startswith("[http"):
        return prefix, None, rest
    return line, None, None


def _marker_core_without_url(line: str) -> str:
    """Title/marker text with any trailing [https://...] removed."""
    prefix, inline_url, open_frag = _split_trailing_inline_url(line)
    if inline_url is not None or open_frag is not None:
        return prefix
    return line


def _is_reading_time_continuation(line: str) -> bool:
    """True when line completes a wrapped reading-time marker (URL optional)."""
    return bool(
        _READING_TIME_CONTINUATION_RE.match(_marker_core_without_url(line).strip())
    )


def _take_trailing_url_from_line(
    lines: list[str], index: int, line: str, title_parts: list[str]
) -> tuple[Optional[str], int] | None:
    """
    If line has a trailing bracket URL, append marker prefix to title_parts and
    return (url, next_index). Otherwise return None.
    """
    prefix, inline_url, open_frag = _split_trailing_inline_url(line)
    if inline_url is None and open_frag is None:
        return None
    if prefix:
        title_parts.append(prefix)
    if inline_url is not None:
        return inline_url, index + 1
    assert open_frag is not None
    url, after = _consume_bracket_url_fragment(lines, index, open_frag)
    return url, after


def _consume_title_and_url(
    lines: list[str], start: int
) -> tuple[str, Optional[str], int]:
    """
    Consume an inline-era title starting at start.

    URL may appear:
    - on the following line(s): TITLE\\n[https://...]
    - trailing on the title line: TITLE (N MINUTE READ) [https://...]
    - after a wrapped marker: TITLE (N\\nMINUTE READ) [https://...]
    - with a wrapped URL body across lines after '['
    """
    title_parts: list[str] = []
    first = lines[start].strip()

    taken = _take_trailing_url_from_line(lines, start, first, title_parts)
    if taken is not None:
        url, after = taken
        return " ".join(title_parts), url, after

    title_parts.append(first)
    j = start + 1

    while j < len(lines):
        nxt = lines[j].strip()
        if not nxt:
            break
        if nxt.startswith("[http"):
            # Classic next-line inline URL.
            break
        if is_section_heading(nxt) or is_emoji_only_line(nxt):
            break

        taken = _take_trailing_url_from_line(lines, j, nxt, title_parts)
        if taken is not None:
            url, after = taken
            return " ".join(title_parts), url, after

        if _is_reading_time_continuation(nxt):
            title_parts.append(nxt)
            j += 1
            continue

        if _looks_like_title_start(nxt) and _TITLE_HINT_RE.search(nxt):
            # Another article title starting (has its own markers).
            break

        joined_so_far = " ".join(title_parts)
        if _TITLE_HINT_RE.search(joined_so_far) and not _TITLE_HINT_RE.search(nxt):
            # Likely finished title markers; stop unless clearly continuation.
            if nxt.isupper() or len(nxt) < 40:
                title_parts.append(nxt)
                j += 1
                continue
            break

        title_parts.append(nxt)
        j += 1
        if j - start > 6:
            break

    return " ".join(title_parts), None, j


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

        title_joined, url_raw, after_title = _consume_title_and_url(lines, i)
        src_line = line_offset + i + 1

        # Require a recognizable article marker for inline-era titles.
        if not _TITLE_HINT_RE.search(title_joined):
            i = after_title
            continue

        reading_time = extract_reading_time(title_joined)
        content_type, is_sponsor = classify_content(title_joined)
        title = strip_markers_from_title(title_joined)

        if url_raw is None:
            url_raw, after_url = _consume_inline_url(lines, after_title)
        else:
            after_url = after_title

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

        k = after_url if url_raw is not None else after_title
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
