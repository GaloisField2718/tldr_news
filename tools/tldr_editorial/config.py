"""Environment-only configuration. Values are never rendered wholesale or logged."""
from __future__ import annotations
import os
from dataclasses import dataclass
from .core import EditorialError


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try: value = int(os.getenv(name, str(default)))
    except ValueError as exc: raise EditorialError(f"invalid_config_{name.lower()}") from exc
    if not lo <= value <= hi: raise EditorialError(f"invalid_config_{name.lower()}")
    return value

@dataclass(frozen=True)
class Config:
    enabled: bool
    api_key: str
    editorial_model: str
    image_model: str
    http_referer: str
    app_title: str
    max_candidates: int
    max_image_bytes: int
    editorial_timeout: int
    image_timeout: int
    max_attempts: int
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket: str
    r2_public_base_url: str
    r2_endpoint: str
    r2_region: str

    @classmethod
    def from_env(cls) -> "Config":
        enabled = os.getenv("TLDR_EDITORIAL_ENABLED", "0") == "1"
        account = os.getenv("CLOUDFLARE_R2_ACCOUNT_ID", "").strip()
        endpoint = os.getenv("CLOUDFLARE_R2_ENDPOINT", "").strip()
        if not endpoint and account:
            endpoint = f"https://{account}.r2.cloudflarestorage.com"
        return cls(
            enabled, os.getenv("OPENROUTER_API_KEY", ""),
            os.getenv("OPENROUTER_EDITORIAL_MODEL", "openai/gpt-5.6-luna"),
            os.getenv("OPENROUTER_IMAGE_MODEL", "google/gemini-3.1-flash-lite-image"),
            os.getenv("OPENROUTER_HTTP_REFERER", ""), os.getenv("OPENROUTER_APP_TITLE", "TLDR Daily Index"),
            _int("TLDR_EDITORIAL_MAX_CANDIDATES", 60, 1, 200),
            _int("TLDR_EDITORIAL_MAX_IMAGE_BYTES", 2_000_000, 1_000, 20_000_000),
            _int("TLDR_EDITORIAL_REQUEST_TIMEOUT_SECONDS", 90, 1, 600),
            _int("TLDR_IMAGE_REQUEST_TIMEOUT_SECONDS", 180, 1, 900),
            _int("TLDR_EDITORIAL_MAX_AUTOMATIC_ATTEMPTS", 1, 1, 5),
            account, os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID", ""), os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", ""),
            os.getenv("CLOUDFLARE_R2_BUCKET", "tldr-daily-assets"), os.getenv("CLOUDFLARE_R2_PUBLIC_BASE_URL", "").rstrip("/"),
            endpoint, os.getenv("CLOUDFLARE_R2_REGION", "auto"),
        )

    def require_openrouter(self) -> None:
        if not self.api_key: raise EditorialError("openrouter_key_missing")

    def require_r2(self) -> None:
        if not all((self.r2_account_id or self.r2_endpoint, self.r2_access_key_id, self.r2_secret_access_key, self.r2_public_base_url)):
            raise EditorialError("r2_configuration_missing")
