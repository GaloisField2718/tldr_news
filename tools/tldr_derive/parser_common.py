"""Shared parsing helpers for TLDR plaintext newsletters."""

from __future__ import annotations

import re
from typing import Optional

from .sanitizer import decode_entities, strip_zero_width

SECTION_ALLOWLIST = {
    "BIG TECH & STARTUPS",
    "SCIENCE & FUTURISTIC TECHNOLOGY",
    "HEADLINES & LAUNCHES",
    "NEWS & TRENDS",
    "MARKETS & BUSINESS",
    "INNOVATION & LAUNCHES",
    "GUIDES & TUTORIALS",
    "RESEARCH & INNOVATION",
    "ENGINEERING & RESOURCES",
    "ATTACKS & VULNERABILITIES",
    "HEADLINES & TRENDS",
    "TOOLS & RESOURCES",
    "DEEP DIVES & ANALYSIS",
    "ENGINEERING & RESEARCH",
    "LAUNCHES & TOOLS",
    "STRATEGIES & TACTICS",
    "RESOURCES & TOOLS",
    "OPINIONS & TUTORIALS",
    "ARTICLES & TUTORIALS",
    "OPINIONS & ADVICE",
    "PROGRAMMING, DESIGN & DATA SCIENCE",
    "QUICK LINKS",
    "MISCELLANEOUS",
    "FEATURES & DESIGNS",
    "ADS & MISCELLANEOUS",
}

_SECTION_RE = re.compile(r"^[A-Z0-9][A-Z0-9 &,/'\-]{2,100}$")
_EMOJI_LINE_RE = re.compile(
    r"^[\U0001F300-\U0001FAFF\U00002700-\U000027BF\u2600-\u26FF\uFE0F\u200D\s]+$"
)

READING_TIME_RE = re.compile(
    r"\((\d+)\s*MINUTE(?:S)?\s+READ\)",
    re.IGNORECASE,
)

CONTENT_MARKER_RE = re.compile(
    r"\((SPONSOR|GITHUB\s+REPO|GITHUB\s+REPOSITORY|COURSE|TOOL|PRODUCT\s+HUNT|"
    r"WEBSITE|APP|REPO)\)",
    re.IGNORECASE,
)

H1_RE = re.compile(r"^#\s+Articles\s+(.+?)\s+(\d{2}-\d{2}-\d{4})\s*$")


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = strip_zero_width(text)
    text = decode_entities(text)
    return text


def slugify_heading(heading: str) -> str:
    slug = heading.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "section"


def classify_content(title: str) -> tuple[str, bool]:
    """Return (content_type, is_sponsor)."""
    upper = title.upper()
    is_sponsor = "(SPONSOR)" in upper
    if is_sponsor:
        return "sponsor", True
    if "GITHUB REPO" in upper or "GITHUB REPOSITORY" in upper:
        return "github_repo", False
    if "(COURSE)" in upper:
        return "course", False
    if "(TOOL)" in upper or "(APP)" in upper or "(WEBSITE)" in upper:
        return "tool", False
    return "editorial", False


def strip_markers_from_title(title: str) -> str:
    title = READING_TIME_RE.sub("", title)
    title = CONTENT_MARKER_RE.sub("", title)
    title = re.sub(r"\s+", " ", title).strip(" -:\t")
    return title


def extract_reading_time(title: str) -> Optional[int]:
    match = READING_TIME_RE.search(title)
    if not match:
        return None
    return int(match.group(1))


def is_emoji_only_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(_EMOJI_LINE_RE.match(stripped))


def is_section_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or is_emoji_only_line(stripped):
        return False
    # Drop leading emoji clusters then re-check.
    without_emoji = re.sub(
        r"^[\U0001F300-\U0001FAFF\U00002700-\U000027BF\u2600-\u26FF\uFE0F\u200D\s]+",
        "",
        stripped,
    ).strip()
    candidate = without_emoji or stripped
    if candidate in SECTION_ALLOWLIST:
        return True
    if candidate.upper() != candidate:
        return False
    if not _SECTION_RE.match(candidate):
        return False
    if len(candidate) > 48:
        return False
    if not re.search(r"[A-Z]", candidate):
        return False
    if candidate in {"TLDR", "SIGN UP", "ADVERTISE", "VIEW ONLINE", "JOBS", "HIRE"}:
        return False
    if candidate.startswith("TLDR"):
        return False
    # Heuristic sections are narrowly shaped like "FOO & BAR" to avoid treating
    # wrapped ALL-CAPS article titles as headings.
    if "&" in candidate:
        return True
    return False


def normalize_section_heading(line: str) -> str:
    stripped = line.strip()
    without_emoji = re.sub(
        r"^[\U0001F300-\U0001FAFF\U00002700-\U000027BF\u2600-\u26FF\uFE0F\u200D\s]+",
        "",
        stripped,
    ).strip()
    return without_emoji or stripped


def detect_format_family(text: str) -> str:
    if re.search(r"(?m)^Links:\s*$", text) and re.search(
        r"(?m)^\[\d+\]\s+https?://", text
    ):
        return "links_block"
    if re.search(r"(?m)^\[https?://", text) or re.search(
        r"MINUTE READ\)\s*\n\s*\[https?://", text, re.IGNORECASE
    ):
        return "inline_url"
    if re.search(r"MINUTE READ\)\s*\[\d+\]", text, re.IGNORECASE):
        return "links_block"
    return "unknown"


def extract_issue_title(sector: str, date_iso: str, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Prefer body date line like "TLDR AI 2026-07-16"
        m = re.match(
            rf"^TLDR(?:\s+.+?)?\s+{re.escape(date_iso)}\s*$",
            stripped,
            re.IGNORECASE,
        )
        if m:
            return stripped
        m2 = re.match(r"^DAILY(?:\s+\w+)?\s+UPDATE\s+(\d{4}-\d{2}-\d{2})\s*$", stripped)
        if m2:
            return f"{sector} {m2.group(1)}"
    # Fallback from H1
    for line in text.splitlines()[:5]:
        m = H1_RE.match(line.strip())
        if m:
            return f"Articles {m.group(1)} {m.group(2)}"
    return f"{sector} {date_iso}"


def skip_preamble(lines: list[str]) -> int:
    """Return index where editorial body likely begins (first section or article)."""
    for i, line in enumerate(lines):
        if is_section_heading(line):
            return i
        if is_emoji_only_line(line):
            # next non-empty may be section
            continue
        upper = line.strip().upper()
        if "MINUTE READ" in upper or "(SPONSOR)" in upper or "(GITHUB" in upper:
            return i
    # Fall back: after Sign Up / TLDR brand block
    for i, line in enumerate(lines):
        if re.match(r"^TLDR(?:\s|$)", line.strip(), re.IGNORECASE):
            return min(i + 1, len(lines))
    return 0
