# Backfill report

## Summary

Historical derived-data backfill for all approved TLDR Markdown issues into
`generated/`, using the derivation tooling already on `main`. No parser changes
and no production-pipeline changes.

| Item | Value |
|------|-------|
| Base commit (`main`) | `ddf9df70f95411b5cc8ff2f5a66083f84d92c19d` |
| Branch | `feat/tldr-derived-data-backfill` |
| Generation command | `PYTHONPATH=. python3 -m tools.tldr_derive generate --all --output generated` |
| Generation exit code | `0` |
| Selected / written | `5928` / `5928` |
| Failures during generate | `0` |

## Generated dataset

| Metric | Value |
|--------|------:|
| Manifest files | 1 (`generated/manifest.json`) |
| Manifest issue entries | 5928 |
| Issue JSON files | 5928 |
| Total generated size (manifest + issues) | 77,887,778 bytes (~74.3 MiB) |
| GoDaddy pollution outputs | 0 |

### Parse status

| Status | Count |
|--------|------:|
| complete | 5597 |
| partial | 327 |
| failed | 4 |

### Format family

| Family | Count |
|--------|------:|
| links_block | 5176 |
| inline_url | 751 |
| unknown | 1 |

### Counts by sector

| Sector | Count |
|--------|------:|
| TLDR | 860 |
| TLDR AI | 828 |
| TLDR Crypto | 758 |
| TLDR Marketing | 731 |
| TLDR Design | 728 |
| TLDR Web Dev | 584 |
| TLDR InfoSec | 505 |
| TLDR Founders | 468 |
| TLDR Product | 261 |
| TLDR Dev | 196 |
| TLDR Cybersecurity | 9 |

## Incremental check

```bash
PYTHONPATH=. python3 -m tools.tldr_derive generate --changed --output generated
```

Exit code `0`. Output summary:

```json
{
  "selected": 0,
  "written": 0,
  "skipped": 0,
  "failures": []
}
```

## Tests and validation

| Command | Exit code | Result |
|---------|----------:|--------|
| `python3 -m unittest tests_derive.test_derive` | 0 | Ran 41 tests, OK |
| `python3 -m tools.tldr_derive validate --all --strict-privacy` | 0 | `processed_count=5928`, `error_count=0`, `privacy_hits=[]` |

Additional structural checks:

- every manifest `derived_path` exists
- every issue JSON is valid UTF-8 JSON
- issue IDs, source paths, and derived paths are unique
- no `.tmp`, `__pycache__`, `.pyc`, or log artifacts under `generated/`

## Source and production immutability

- Approved source Markdown inventory count: **5928**
- Combined inventory hash unchanged:
  `69249e843a15ba4bd0697598e76320ede0b2fb16347b570bbf77f392c7dd7787`
- Sealed production file hashes unchanged vs base commit:
  `script.py`, `automation.sh`, `push_script.sh`, `cronjob`, `Pipfile.lock`

No IMAP or network ingestion scripts were executed.

## Spot checks

Inspected:

- 5 recent `links_block` issues (2026-07-17 samples across sectors)
- 5 historical `inline_url` issues (2023-01)
- one latest issue from every sector (11 sectors)
- all 4 `failed` issues
- 10 `partial` issues
- one sponsor-containing issue (`tldr:2026-07-17`, 4 sponsor items)
- one multiline-capable modern issue (`tldr:2024-03-15`)

Observed article/issue fields present as expected when content was extracted:

- issue `date`, `sector`, `sections`
- article `title`, `summary`
- `url` when resolved
- `reading_time_minutes` when available

All spot-checked documents had the expected JSON field shape (`ok_fields=true`).

## Known anomalies (documented only; not fixed in this PR)

1. **Failed issues (4)**  
   - `tldr:2023-01-17` (header-only / unknown format)  
   - `tldr-crypto:2023-02-23`  
   - `tldr-crypto:2023-02-24`  
   - `tldr-crypto:2023-02-27`
2. **Partial issues (327)** mostly historical `inline_url` era with
   `missing_inline_url` / related warnings; still emit useful partial content.
3. **Sponsor/nav bleed into `GENERAL`** on some complete modern issues (CTA /
   sponsor intro lines classified as articles). Existing parser behavior; not
   changed here.
4. **`TLDR Cybersecurity`** remains a tiny historical sector (9 issues only).

## Diff summary

Intended committed changes:

- `.gitignore` — allow committing `generated/` dataset; keep caches/temps ignored
- remove `generated/.gitkeep`
- add `generated/manifest.json`
- add `generated/issues/**/*.json` (5928 files)
- add `docs/reports/BACKFILL_REPORT.md`

Not changed:

- `tools/tldr_derive` parser behavior
- newsletter Markdown sources
- sealed production ingestion files
- legacy diagnostic scripts
