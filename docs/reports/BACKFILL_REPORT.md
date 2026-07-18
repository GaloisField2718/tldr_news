# Backfill report

## Summary

Historical derived-data backfill for all approved TLDR Markdown issues into
`generated/`, using derivation tooling on `main` at generator **0.1.3**.

This regeneration follows two merged parser fixes that were required before a
correct historical backfill:

1. **Same-line historical inline URLs** (PR #5) — titles of the form
   `TITLE (N MINUTE READ) [https://...]` (including wrapped reading-time
   markers) now emit a normalized article `url` for any `http(s)` host.
2. **Job-board footer false positive** (PR #6) — sponsor copy beginning
   `job board. Thousands of engineers...` no longer truncates the rest of the
   edition; standalone `JOB BOARD` / `JOBS BOARD` headings still truncate.

No further parser changes were made on this backfill branch. No production-
pipeline changes.

| Item | Value |
|------|-------|
| Base commit (`main`) | `e950e5f4c8baaeac6d59b5a904eb9045737e0e65` |
| Branch | `feat/tldr-derived-data-backfill` |
| Generator version | `0.1.3` |
| Schema version | `1.0.0` |
| Generation command | `PYTHONPATH=. python3 -m tools.tldr_derive generate --all --output generated` |
| Generation exit code | `0` |
| Selected / written | `5929` / `5929` |
| Failures during generate | `0` |

Inventory note: source count is **5929** (was 5928 at the first backfill
attempt) because `TLDR AI/article_17-07-2026.md` landed on `main` with the
parser-fix merges.

## Generated dataset

| Metric | Value |
|--------|------:|
| Manifest files | 1 (`generated/manifest.json`) |
| Manifest issue entries | 5929 |
| Issue JSON files | 5929 |
| `generator_version` on every issue + manifest | `0.1.3` |
| Total generated size (manifest + issues) | 77,897,303 bytes (~74.3 MiB) |
| GoDaddy pollution outputs | 0 |

### Parse status

| Status | Count |
|--------|------:|
| complete | 5903 |
| partial | 22 |
| failed | 4 |

### Format family

| Family | Count |
|--------|------:|
| links_block | 5177 |
| inline_url | 751 |
| unknown | 1 |

### Counts by sector

| Sector | Count |
|--------|------:|
| TLDR | 860 |
| TLDR AI | 829 |
| TLDR Crypto | 758 |
| TLDR Marketing | 731 |
| TLDR Design | 728 |
| TLDR Web Dev | 584 |
| TLDR InfoSec | 505 |
| TLDR Founders | 468 |
| TLDR Product | 261 |
| TLDR Dev | 196 |
| TLDR Cybersecurity | 9 |

### archive.ph editorial URLs

| Metric | Count |
|--------|------:|
| Emitted article `url` values starting with `https://archive.ph/` | 369 |

Recovered after the footer fix (present in generated output):

- `archive.ph/TvP3p` — `TLDR/article_27-01-2023.md`
- `archive.ph/5dgFD` — `TLDR/article_27-01-2023.md`
- `archive.ph/jErjz` — `TLDR/article_30-01-2023.md`
- `archive.ph/ukO06` — `TLDR/article_31-01-2023.md`

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
| `python3 -m unittest tests_derive.test_derive` | 0 | Ran 46 tests, OK |
| `python3 -m tools.tldr_derive validate --all --strict-privacy` | 0 | `processed_count=5929`, `error_count=0`, `privacy_hits=[]` |

Additional structural checks:

- every manifest `derived_path` exists
- every issue JSON is valid UTF-8 JSON
- every issue and the manifest report `generator_version=0.1.3`
- issue IDs, source paths, and derived paths are unique
- no `.tmp`, `__pycache__`, `.pyc`, or log artifacts under `generated/`

## Source and production immutability

- Approved source Markdown inventory count: **5929**
- Combined inventory hash:
  `b57251b20222580ca715116ce32c71eee86b2400dd5467abdc2f03ab44e88bc3`
- This backfill commit only updates `generated/` and this report (plus prior
  `.gitignore` allowance for `generated/`). Parser code is whatever `main`
  already contains after PRs #5 and #6.

No IMAP or network ingestion scripts were executed. Sealed production files
(`script.py`, `automation.sh`, `push_script.sh`, `cronjob`) were not modified.

## Comparison to obsolete 0.1.1 backfill draft

| Metric | 0.1.1 draft | 0.1.3 final |
|--------|------------:|------------:|
| Issues | 5928 | 5929 |
| complete | 5597 | 5903 |
| partial | 327 | 22 |
| failed | 4 | 4 |
| archive.ph URLs emitted | 236 | 369 |
| `missing_inline_url` (validate era) | 515 | 9 |

## Known anomalies (documented only; not fixed in this PR)

1. **Failed issues (4)**  
   - `tldr:2023-01-17` (header-only / unknown format)  
   - `tldr-crypto:2023-02-23`  
   - `tldr-crypto:2023-02-24`  
   - `tldr-crypto:2023-02-27`
2. **Partial issues (22)** remain after the inline/footer fixes; still emit
   useful partial content.
3. **Sponsor/nav bleed into `GENERAL`** on some complete modern issues (CTA /
   sponsor intro lines classified as articles). Existing parser behavior; not
   changed here.
4. **`TLDR Cybersecurity`** remains a tiny historical sector (9 issues only).
5. Some multiline historical titles still lose leading title lines (e.g. wrap
   before `(N MINUTE READ)`), while the editorial URL is correctly emitted —
   separate from this backfill scope.

## Diff summary

Intended committed changes on this branch:

- `.gitignore` — allow committing `generated/` dataset; keep caches/temps ignored
- `generated/manifest.json` + `generated/issues/**/*.json` (5929 files)
- `docs/reports/BACKFILL_REPORT.md` (this file)

Not changed in the backfill commit itself:

- newsletter Markdown sources (beyond what already landed on `main`)
- sealed production ingestion files
- legacy diagnostic scripts
- additional parser edits beyond PRs #5 / #6 already on `main`
