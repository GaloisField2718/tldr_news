# Daily editorial and illustration source pipeline

## Ownership and flow

`tldr_news` owns normalized source data, bounded candidate construction, OpenRouter requests, strict validation, deterministic fallback, image validation, R2 publication, idempotence/retry state, and generated contracts. Private Cloudflare R2 owns image binaries. The read-only Worker owns public `workers.dev` delivery. `tldr-news-web` remains responsible for layout, responsive images, Open Graph, and browser fallbacks; it is intentionally not changed here.

```text
generated/issues JSON -> normalized validation -> balanced dossier
  -> optional GPT-5.6 Luna strict plan -> local plan validation
  -> fixed application style prompt + semantic brief
  -> optional Gemini image -> strict WebP validation -> temporary 0600 file
  -> immutable R2 key -> HEAD/upload/HEAD verification
  -> atomic editorial JSON + atomic manifest -> consistency validation -> Git
```

Images are never stored in Git, `generated/editorial/images`, Vercel Blob, or permanent VPS storage. No personal DNS migration is needed.

## Verified external contracts (2026-07-21)

Official OpenRouter documentation confirms non-streaming Chat Completions at `https://openrouter.ai/api/v1/chat/completions`, strict `response_format.type=json_schema` with `json_schema.strict=true`, and `provider.require_parameters=true`. Image generation uses the current dedicated `POST https://openrouter.ai/api/v1/images` contract, not Chat Completions. Before each live image request, one client instance performs bounded authenticated discovery through `GET /api/v1/images/models` and the selected model's declared `GET /api/v1/images/models/{model}/endpoints` path; the result is cached for that publication run. The configured model must exist and one endpoint must explicitly support `n=1`, `resolution=1K`, `aspect_ratio=3:2`, and `output_format=webp`. Optional compression/background are sent only when that endpoint advertises them, and provider routing is pinned without fallback. The official model catalog currently contains both requested exact IDs:

- `openai/gpt-5.6-luna` (structured outputs, response format, reasoning controls);
- `google/gemini-3.1-flash-lite-image` (text+image output).

No substitution is made. If the image model or required publication capabilities are absent, generation fails safely into `generation_failed`. At review time the requested Gemini model exists, but its endpoint capability response does not advertise `output_format=webp`; live publication therefore remains safely unavailable unless OpenRouter advertises that required capability. References: [API](https://openrouter.ai/docs/api/reference/overview), [structured outputs](https://openrouter.ai/docs/features/structured-outputs), [image generation](https://openrouter.ai/docs/features/multimodal/images), [image models](https://openrouter.ai/api/v1/images/models), and [models API](https://openrouter.ai/api/v1/models).

Cloudflare's official [S3 compatibility](https://developers.cloudflare.com/r2/api/s3/api/) and [authentication](https://developers.cloudflare.com/r2/api/s3/tokens/) docs specify `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`, region `auto`, and access-key credentials. The implementation uses locked boto3 rather than implementing SigV4. Worker binding and Wrangler configuration follow the official [R2 Workers API](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/) and [Wrangler configuration](https://developers.cloudflare.com/workers/wrangler/configuration/) docs.

## Configuration

```text
TLDR_EDITORIAL_ENABLED=0
OPENROUTER_API_KEY=
OPENROUTER_EDITORIAL_MODEL=openai/gpt-5.6-luna
OPENROUTER_IMAGE_MODEL=google/gemini-3.1-flash-lite-image
OPENROUTER_HTTP_REFERER=
OPENROUTER_APP_TITLE=TLDR Daily Index
TLDR_EDITORIAL_MAX_CANDIDATES=60
TLDR_EDITORIAL_MAX_IMAGE_BYTES=2000000
TLDR_EDITORIAL_REQUEST_TIMEOUT_SECONDS=90
TLDR_IMAGE_REQUEST_TIMEOUT_SECONDS=180
TLDR_EDITORIAL_MAX_AUTOMATIC_ATTEMPTS=1
CLOUDFLARE_R2_ACCOUNT_ID=
CLOUDFLARE_R2_ACCESS_KEY_ID=
CLOUDFLARE_R2_SECRET_ACCESS_KEY=
CLOUDFLARE_R2_BUCKET=tldr-daily-assets
CLOUDFLARE_R2_PUBLIC_BASE_URL=
CLOUDFLARE_R2_ENDPOINT=
CLOUDFLARE_R2_REGION=auto
```

The endpoint is derived from account ID when absent. Use a dedicated OpenRouter key with a low account-side spending limit. Restrict the R2 token operationally to this one bucket. Never place either credential set in Git, generated JSON, logs, exception text, prompt snapshots, or CI. CI receives none of these values and performs no OpenRouter/R2 call.

## Candidate and plan contract

Only normalized, complete issues for one selected date are read. Duplicate `(issue_id, article_id)` pairs merge first and sponsor classification wins. Then canonical URLs deduplicate within presentation class after lowercasing host, removing fragments and known tracking parameters, and sorting query parameters. Non-HTTP(S) URLs are rejected. Ordering is TLDR, AI, Dev, Web Dev, InfoSec, Cybersecurity, Crypto, Product, Design, Founders, Marketing, then unknown slugs.

A deterministic round-robin shortlist (default 60) balances present sectors and assigns opaque `c001...` IDs. The compact dossier includes only ID, sector, section, title, summary, source domain, reading time, and class; no URL or raw issue JSON is sent. The controlled corpus mapping is `editorial -> editorial`, `sponsor -> sponsor`, and `github_repo`, `course`, `tool` -> `resource` (the currently observed corpus values are exactly those five). Explicit compatibility aliases `resource`, `library`, `tutorial`, and `job` also remain resource-only. Sponsors and resources never enter front-page or visual positions. Empty summaries are not front-page eligible.

Luna must return exactly the strict object documented in `tools/tldr_editorial/openrouter.py`: lead ID, up to nine ID/role entries, sector order, and semantic visual brief. Local validation independently enforces exact properties/types, one lead, at most four secondaries, eligibility, uniqueness, sector validity, one-to-three selected visual sources, bounded strings/lists, and no controls, URL, markup, sponsor, or unavailable ID. Provider reasoning is excluded and never persisted. Invalid output is discarded wholesale.

Fallback is stable: complete editorial candidates only, TLDR lead preference, distinct-sector secondaries, maximum nine, then briefs. Luna failure skips images and is persisted so cron does not retry every minute.

## Illustration and R2

Application code prepends a versioned serious-newspaper illustration style (not photography; one focal subject; no words, logos, interfaces, charts, watermarks, named-artist imitation, fabricated evidence, or unrelated collage), then appends exact source titles/summaries and Luna's subject, metaphor, composition, and forbidden elements. Headlines are never requested in pixels. The safe final prompt and SHA-256 are recorded.

The dedicated Images API receives top-level `model`, `prompt`, `n`, `resolution`, `aspect_ratio`, `output_format`, and supported optional image fields. Exactly one `data` entry with `b64_json` is accepted. One 1K, 3:2 WebP (opaque/compression 82 where advertised) is requested. Strict base64 and RIFF/WebP headers, dimensions (256–8192), ratio tolerance, media type, single-image count, and maximum 2,000,000 bytes are validated before upload. The temporary `0600` file is always deleted. Editorial, capability, and image JSON responses use strict byte-limited readers; the image limit is derived from the configured binary maximum plus bounded base64/JSON overhead.

Keys are content-addressed and immutable:

```text
daily/YYYY/MM/DD/<full-image-sha256>.webp
```

The client rejects traversal/backslashes/control characters. It HEADs first, verifies/reuses a matching object, or uploads with `Content-Type: image/webp`, `Cache-Control: public, max-age=31536000, immutable`, and SHA/dimension/date/generator metadata, then HEAD-verifies size/type/SHA metadata. ETag is not treated as SHA-256. Verification failure cannot produce `ready`. Upload-before-Git may leave an immutable orphan; normal publication never deletes objects. `storage-report --list-r2` reports candidates only. Deletion is deliberately deferred and must be manual, age-gated, confirmed, and restricted to `daily/`.

## Artifacts, idempotence, retries

`generated/editorial/YYYY/YYYY-MM-DD.json` contains schema/generator/date/status, source/model/prompt hashes, canonical source refs, plan, illustration identity and delivery URL, usage including actual provider cost, request IDs, sanitized failure code, and prompt checksum. Status is `ai_complete`, `editorial_only`, `deterministic_fallback`, or `disabled`; illustration status is `ready`, `not_requested`, `disabled`, `generation_failed`, `validation_failed`, `upload_failed`, or `storage_verification_failed`.

`generated/editorial/manifest.json` has one sorted date entry with artifact path/SHA/bytes/status, both input hashes, and nullable image key/URL/SHA/bytes. JSON is canonical UTF-8 with one newline and atomic `os.replace`; containment and symlink escapes are rejected. A missing manifest is valid only for an output tree containing no files at all.

Editorial hash covers canonical bounded dossier + editorial model + editorial prompt version + output-schema version. Offline consistency reconstructs that dossier from current normalized data and rejects stale hashes after title, summary, membership, configured model, or controlled-version changes. For artifacts with an illustration hash, it also reconstructs temporary visual-source IDs, exact current source titles/summaries, and current image configuration to validate the illustration hash. Illustration hash covers validated brief + selected titles/summaries + image model + illustration prompt version + image configuration. Public base URL is excluded, so changing it only updates the derived URL. Matching hashes preserve bytes/mtime and make zero model/R2 calls. A failed hash is attempted once automatically; `--retry-image` explicitly retries only its image stage. `--force` and `--retry-image` are never cron flags. Prompt-version changes affect only dates explicitly processed; default is latest, with no historical backfill.

## Commands

```bash
# Offline deterministic preview (no writes/network)
python3 -m tools.tldr_editorial generate --latest --offline --dry-run

# Disabled/fallback artifact
TLDR_EDITORIAL_ENABLED=0 python3 -m tools.tldr_editorial generate --latest

# Explicit first live generation
TLDR_EDITORIAL_ENABLED=1 python3 -m tools.tldr_editorial generate --latest --require-live

# Explicit image retry
TLDR_EDITORIAL_ENABLED=1 python3 -m tools.tldr_editorial generate --latest --retry-image --require-live

# Offline consistency
python3 -m tools.tldr_editorial validate --all --output generated/editorial

# Optional live HEAD verification
python3 -m tools.tldr_editorial validate --all --output generated/editorial --verify-storage

# Offline references / optional live orphan report
python3 -m tools.tldr_editorial storage-report
python3 -m tools.tldr_editorial storage-report --list-r2
```

`--date YYYY-MM-DD`, `--latest`, `--force`, `--retry-image`, `--dry-run`, `--offline`, and `--require-live` are supported. Live mode is forbidden when `CI` is set. Before first live use: pass tests, review dry-run, ensure clean output/Git state, select one date, and explicitly use `--require-live`.

## Operations, activation, and rollback

Deploy/test the Worker per its README, set the Worker base URL and bucket-restricted VPS credentials, perform one manual live generation and live storage validation, then enable `TLDR_EDITORIAL_ENABLED=1` on the VPS. Do not alter cron automatically. `push_script.sh` (not `automation.sh`) runs normalized validation before generation, validates/stages only editorial JSON, and repeats derivation/editorial checks after rebase. Expected provider/storage failures are serialized as valid exit-zero fallback states. Any non-zero editorial CLI result is internal/structural, is never swallowed, and blocks both pre-rebase commit and post-rebase push.

Rollback by disabling `TLDR_EDITORIAL_ENABLED`, reverting pipeline commits normally, and deploying a prior Worker version; immutable objects can remain. Rotate a compromised OpenRouter key by revoking it, creating a low-limit replacement, and updating only VPS secret storage. Rotate R2 keys similarly with one-bucket scope. For compromise, delete the old credential immediately and inspect provider logs; do not paste key values into tickets or PRs. Worker rollback does not require DNS changes. Historical images are not generated by default.
