# TLDR derived-data contract

## Purpose

This contract describes the JSON documents produced by
`python3 -m tools.tldr_derive` from immutable TLDR newsletter Markdown sources.

The Markdown files under approved `TLDR` / `TLDR *` directories remain the source of
truth. Derived JSON is a best-effort, offline projection for a future web reader.

## Versions

- `schema_version`: `1.0.0`
- `generator_version`: `0.1.1` (embedded in each issue document)

## Ordering convention

`sections[].order` and section-local `articles[].order` are **1-based**.

- The first section in document order has `order: 1`.
- The first article within a section has `order: 1`.

## Issue document

Required fields:

| Field | Type | Notes |
|-------|------|-------|
| `schema_version` | string | Currently `1.0.0` |
| `generator_version` | string | Generator release id |
| `issue_id` | string | `{sector_slug}:{YYYY-MM-DD}` |
| `sector` | string | Directory name, e.g. `TLDR AI` |
| `sector_slug` | string | e.g. `tldr-ai` |
| `date` | string | ISO `YYYY-MM-DD` |
| `source_path` | string | Repo-relative Markdown path (traceability only) |
| `source_content_hash` | string | `sha256:` + hex digest of source bytes |
| `format_family` | string | `links_block` \| `inline_url` \| `unknown` |
| `parse_status` | string | `complete` \| `partial` \| `failed` |
| `parse_warnings` | array | Structured warnings (may be empty) |
| `title` | string | Issue display title |
| `sections` | array | Ordered sections |

Explicitly excluded from deterministic issue outputs:

- `generated_at`
- `url_raw`
- `articles_flat`
- embedded raw Markdown bodies

### Warning object

```json
{
  "code": "dangling_reference",
  "message": "Reference 8 has no link definition",
  "line": 42
}
```

`line` may be `null` when unavailable.

### Section object

| Field | Type | Required |
|-------|------|----------|
| `id` | string | yes |
| `heading` | string | yes |
| `order` | integer (1-based) | yes |
| `articles` | array | yes |

### Article object

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | `{issue_id}:a{NN}` or `{issue_id}:o{NNN}` |
| `order` | integer | yes | 1-based within section |
| `title` | string | yes | Markers stripped |
| `summary` | string | yes | May be empty string |
| `url` | string \| null | yes | Sanitized public http(s) URL or `null` |
| `reading_time_minutes` | integer \| null | yes | From `(N MINUTE READ)` when present |
| `source_domain` | string \| null | yes | Host without leading `www.` |
| `content_type` | string | yes | `editorial` \| `sponsor` \| `github_repo` \| `course` \| `tool` |
| `is_sponsor` | boolean | yes | |

Unresolved optional values use JSON `null` consistently.

## Parse status

- `complete`: editorial articles extracted without material warnings
- `partial`: useful content extracted, but material warnings remain
- `failed`: recognized TLDR issue path, but no useful article content

Unrelated directories are ignored by discovery and are never marked `failed`.

## Privacy rules

Generated outputs must not contain:

- unsubscribe URLs
- subscription management / preference URLs
- URLs with subscriber `email=` parameters
- signed personal subscription links
- referral/account-management hosts such as `refer.tldr.tech` and `hub.sparklp.co`

Ordinary editorial URLs keep functional query parameters (including `t`, `p`, `s`,
`token`, `uid`, and `user_id`) after HTML-entity decoding and wrap repair.
Subscriber-identifying parameters (`email`, `subscriber`, `subscriber_id`) are
stripped so they never appear in generated artifacts. Redirects are never resolved
over the network.

## Manifest

`generated/manifest.json`:

```json
{
  "schema_version": "1.0.0",
  "generator_version": "0.1.1",
  "issues": [
    {
      "issue_id": "tldr-ai:2026-07-16",
      "sector": "TLDR AI",
      "sector_slug": "tldr-ai",
      "date": "2026-07-16",
      "source_path": "TLDR AI/article_16-07-2026.md",
      "source_content_hash": "sha256:...",
      "schema_version": "1.0.0",
      "generator_version": "0.1.1",
      "format_family": "links_block",
      "parse_status": "complete",
      "derived_path": "issues/tldr-ai/2026/2026-07-16.json"
    }
  ]
}
```

`--changed` regenerates a source when its content hash changes, its derived JSON is
missing, or the entry's `schema_version` / `generator_version` differs from the
current generator.

## Output layout

```text
generated/
  manifest.json
  issues/
    tldr-ai/
      2026/
        2026-07-16.json
```

## Determinism

- UTF-8 JSON
- 2-space indent
- trailing newline
- stable field order as emitted by the generator
- stable sorting of issues/warnings
- no timestamps in issue documents

Running generation twice against unchanged sources must produce no diff.
