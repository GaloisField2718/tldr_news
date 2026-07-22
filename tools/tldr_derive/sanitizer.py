"""URL privacy sanitization and HTML/entity cleanup."""

from __future__ import annotations

import html
import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Zero-width / BOM characters commonly injected in TLDR preheaders.
_ZW_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")

_SPARKLP_RE = re.compile(r"(^|\.)hub\.sparklp\.co$", re.IGNORECASE)
_REFER_RE = re.compile(r"(^|\.)refer\.tldr\.tech$", re.IGNORECASE)
_TLDR_TECH_RE = re.compile(r"(^|\.)tldr\.tech$", re.IGNORECASE)
_TLDR_NEWSLETTER_RE = re.compile(r"(^|\.)tldrnewsletter\.com$", re.IGNORECASE)

# Subscriber-identifying query keys stripped only on management/newsletter hosts.
_SUBSCRIBER_PARAM_KEYS = {
    "email",
    "subscriber",
    "subscriber_id",
}

_CREDENTIAL_PARAM_KEYS = {
    "access_token", "refresh_token", "id_token", "api_key", "apikey",
    "client_secret", "auth_token", "authorization", "password", "passwd",
    "session", "session_id", "sessionid", "jwt", "signature",
    "x-amz-signature", "x-amz-credential", "x-amz-security-token",
    "x-goog-signature", "x-goog-credential",
}
_OBSERVED_PUBLIC_CANONICAL = {
    ("stratechery.com", "access_token"),
    ("www.stratechery.com", "access_token"),
}

_PRIVATE_PATH_RE = re.compile(
    r"(^|/)(unsubscribe|manage|preferences?|account|settings|email-preferences)"
    r"(/|$|\?)",
    re.IGNORECASE,
)


def strip_zero_width(text: str) -> str:
    return _ZW_RE.sub("", text)


def decode_entities(text: str) -> str:
    once = html.unescape(text)
    twice = html.unescape(once)
    return twice


def repair_wrapped_url(raw: str) -> str:
    """Join a URL that was soft-wrapped across lines or broken by spaces."""
    cleaned = decode_entities(raw)
    cleaned = cleaned.replace("\r", "").replace("\n", "").replace(" ", "")
    cleaned = strip_zero_width(cleaned)
    return cleaned.strip().rstrip(").,;]>\"'")


def _host(netloc: str) -> str:
    return (netloc or "").lower()


def _is_management_host(host: str) -> bool:
    return bool(
        _TLDR_TECH_RE.search(host)
        or _TLDR_NEWSLETTER_RE.search(host)
        or _SPARKLP_RE.search(host)
        or _REFER_RE.search(host)
    )


def is_private_url(url: str) -> bool:
    """True when the URL is a subscription/account/unsubscribe/referral link."""
    if not url:
        return True
    repaired = repair_wrapped_url(url)
    parts = urlsplit(repaired)
    host = _host(parts.netloc)
    path = parts.path or ""
    query = parts.query or ""
    lowered_path_q = f"{path}?{query}".lower()

    if _SPARKLP_RE.search(host) or _REFER_RE.search(host):
        return True

    if _TLDR_NEWSLETTER_RE.search(host):
        if re.search(r"unsubscribe|/manage\b|preferences?|account", lowered_path_q):
            return True
        if re.search(r"(^|&)(email|subscriber|subscriber_id)=", query, re.IGNORECASE):
            return True

    if _TLDR_TECH_RE.search(host):
        if re.search(r"/(manage|unsubscribe|preferences?|account)(/|$|\?)", path, re.I):
            return True
        if re.search(r"(^|&)(email|subscriber|subscriber_id)=", query, re.IGNORECASE):
            # manage?email= and similar on tldr.tech
            if "manage" in path.lower() or "unsubscribe" in path.lower():
                return True

    if _PRIVATE_PATH_RE.search(path) and _is_management_host(host):
        return True

    return False


def normalize_public_url(url: Optional[str]) -> Optional[str]:
    """Return a sanitized http(s) URL, or None if invalid/private/unresolved.

    Ordinary editorial query parameters (including ``t``, ``p``, ``s``, ``token``,
    ``uid``, ``user_id``) are preserved. Subscriber-identifying parameters are
    stripped only on known TLDR/TLDR-newsletter management hosts; fully private
    management/unsubscribe URLs are rejected entirely.
    """
    if url is None:
        return None
    repaired = repair_wrapped_url(url)
    if not repaired:
        return None
    if is_private_url(repaired):
        return None
    parts = urlsplit(repaired)
    if parts.scheme not in ("http", "https"):
        return None
    if not parts.netloc or parts.username is not None or parts.password is not None:
        return None

    host = (parts.hostname or "").lower()
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    credential_keys = {k.lower() for k, _ in query_pairs} & _CREDENTIAL_PARAM_KEYS
    if credential_keys:
        if any((host, key) not in _OBSERVED_PUBLIC_CANONICAL for key in credential_keys):
            return None
        query_pairs = [(k, v) for k, v in query_pairs if k.lower() not in credential_keys]
    if _is_management_host(host):
        query_pairs = [
            (k, v)
            for k, v in query_pairs
            if k.lower() not in _SUBSCRIBER_PARAM_KEYS
        ]
    # Never emit subscriber email/identity params on any host.
    query_pairs = [
        (k, v)
        for k, v in query_pairs
        if k.lower() not in _SUBSCRIBER_PARAM_KEYS
    ]

    new_query = urlencode(query_pairs, doseq=True)
    normalized = urlunsplit(
        (parts.scheme, parts.netloc.lower(), parts.path, new_query, "")
    )
    if is_private_url(normalized):
        return None
    return normalized


def source_domain_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    host = urlsplit(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


_FOOTER_START_RE = re.compile(
    r"(?im)^(?:"
    r"if you don't want to receive|"
    r"if you have any comments or feedback|"
    r"thanks for reading|"
    r"want to advertise|"
    r"if your company is interested in reaching|"
    r"we help cutting edge companies hire|"
    r"click here to unsubscribe|"
    r"manage your subscription|"
    r"unsubscribe here|"
    r"love tldr|"
    r"tell your friends|"
    r"tell friends|"
    r"share tldr|"
    r"if you are in a hiring position|"
    r"if you're hiring|"
    r"hire (ai|tech|software)|"
    # Standalone footer heading only — not "job board. Thousands of engineers..."
    r"jobs? board\.?\s*$|"
    r"careers at tldr"
    r")"
)


def truncate_footer(text: str) -> tuple[str, bool]:
    """Remove trailing subscription/account footer. Returns (text, removed?)."""
    lines = text.splitlines()
    cut = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _FOOTER_START_RE.match(stripped):
            cut = i
            break
        lower = stripped.lower()
        if "unsubscribe" in lower and ("http" in lower or "[" in lower):
            cut = i
            break
        if re.search(r"/manage\?email=", lower):
            cut = i
            break
    if cut is None:
        return text, False
    return "\n".join(lines[:cut]).rstrip() + "\n", True
