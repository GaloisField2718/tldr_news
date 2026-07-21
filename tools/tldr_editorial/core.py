"""Shared constants and safe deterministic I/O for Daily editorial artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
GENERATOR_VERSION = "1.0.0"
EDITORIAL_PROMPT_VERSION = "1.0.0"
ILLUSTRATION_PROMPT_VERSION = "1.0.0"
EDITORIAL_SCHEMA_VERSION = "1.0.0"
IMAGE_CONFIGURATION = {"n":1,"resolution":"1K","aspect_ratio":"3:2","output_format":"webp","output_compression":82,"background":"opaque"}
SECTOR_ORDER = (
    "tldr", "tldr-ai", "tldr-dev", "tldr-web-dev", "tldr-infosec",
    "tldr-cybersecurity", "tldr-crypto", "tldr-product", "tldr-design",
    "tldr-founders", "tldr-marketing",
)
OBJECT_KEY_RE = re.compile(r"daily/(\d{4})/(\d{2})/(\d{2})/([0-9a-f]{64})\.webp\Z")
SHA_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")

class EditorialError(Exception):
    """A safe, user-displayable editorial pipeline error."""


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def hash_parts(*parts: Any) -> str:
    h = hashlib.sha256()
    for part in parts:
        data = part if isinstance(part, bytes) else canonical_bytes(part)
        h.update(len(data).to_bytes(8, "big")); h.update(data)
    return "sha256:" + h.hexdigest()


def contained_path(root: Path, relative: str) -> Path:
    if not relative or "\\" in relative or Path(relative).is_absolute() or any(p in ("", ".", "..") for p in relative.split("/")):
        raise EditorialError("unsafe_relative_path")
    root = root.resolve()
    candidate = root.joinpath(*relative.split("/"))
    # Existing parents and symlinks must remain under root.
    parent = candidate.parent.resolve()
    if root != parent and root not in parent.parents:
        raise EditorialError("path_escape")
    if candidate.is_symlink():
        raise EditorialError("symlink_escape")
    return candidate


def atomic_json(path: Path, value: Any) -> bool:
    data = canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise EditorialError("symlink_escape")
    if path.exists() and path.read_bytes() == data:
        return False
    fd, name = tempfile.mkstemp(prefix=".tldr-editorial-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data); fh.flush(); os.fsync(fh.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        try: os.unlink(name)
        except FileNotFoundError: pass
    return True


def object_key(date: str, sha256: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not SHA_RE.fullmatch(sha256):
        raise EditorialError("invalid_image_identity")
    key = f"daily/{date[0:4]}/{date[5:7]}/{date[8:10]}/{sha256[7:]}.webp"
    validate_object_key(key, date)
    return key


def validate_object_key(key: str, date: str | None = None) -> None:
    if "\\" in key or any(ord(c) < 32 for c in key) or not OBJECT_KEY_RE.fullmatch(key):
        raise EditorialError("invalid_object_key")
    if date and key[6:16].replace("/", "-") != date:
        raise EditorialError("object_key_date_mismatch")
