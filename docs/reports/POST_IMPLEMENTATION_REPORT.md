# Post-implementation report

## 1. Executive summary

PR1 (draft PR #3) delivers an isolated, stdlib-only derivation foundation under
`tools/tldr_derive`, safe offline tests under `tests_derive/`, documentation under
`docs/`, and a safe GitHub Actions workflow. The production IMAP ingestion path was
not modified or executed.

Review corrections on `feat/tldr-derived-data-foundation` add version-aware
`--changed` selection, pathlib containment checks, output-root rejection inside
`TLDR*` trees, editorial URL query preservation, real failure-isolation /
manifest-safety behavior, and clarified validation terminology.

Full-corpus offline validation over **5928** approved TLDR issues completed with
exit code **0** and **0** privacy hits under `--strict-privacy`:

- `complete`: **5597**
- `partial`: **327**
- `failed`: **4**
- format families: `links_block` **5176**, `inline_url` **751**, `unknown` **1**

No full historical backfill was committed.

## 2. Base commit and implementation branch

| Item | Value |
|------|-------|
| Base commit | `db370327ee0f8a787f0a4136e5f8dc37edfb62db` |
| Implementation branch | `feat/tldr-derived-data-foundation` |
| Review-fix commit | `89d6091d37a506a00a18aedbe916c640eb96193f` |
| Branch HEAD after report updates | `167a3a2921126e6b1adf817251b3aae5f4d644fc` |
| Draft PR | #3 (remains draft; not merged) |
| Source inventory count | 5928 |
| Combined inventory hash | `69249e843a15ba4bd0697598e76320ede0b2fb16347b570bbf77f392c7dd7787` |
| Inventory match after review fixes | **True** |

## 3. Files added

- `tools/**` derive package
- `tests_derive/**` safe tests, fixtures, expected samples
- `docs/data-contract.md`
- `docs/reports/PRE_IMPLEMENTATION_REPORT.md`
- `docs/reports/POST_IMPLEMENTATION_REPORT.md`
- `generated/.gitkeep`
- `.github/workflows/derive-ci.yml`

## 4. Files modified

- `.gitignore`
- Review corrections across derive modules/tests/docs as listed in the git history
  of this branch

## 5. Files deliberately unchanged

- `script.py`, `automation.sh`, `push_script.sh`, `cronjob`, `Pipfile.lock`
- all existing newsletter Markdown under approved `TLDR*` directories
- legacy `tests/*` and `archives/*` diagnostic scripts
- `.env` (never read)

## 6. Implemented architecture

Offline generator only:

1. Discover approved top-level `TLDR` / `TLDR *` issue files.
2. Detect format family (`links_block` vs `inline_url`).
3. Best-effort parse into schema-versioned issue JSON.
4. Sanitize URLs/privacy (reject management links; preserve editorial query params).
5. Atomically write under a validated `--output` root.
6. Maintain `manifest.json` with per-entry `schema_version` / `generator_version`
   for incremental `--changed` generation.

## 7. Implemented data contract

See `docs/data-contract.md`.

- `schema_version`: `1.0.0`
- `generator_version`: `0.1.1`
- 1-based section/article ordering
- no `generated_at`, `url_raw`, `articles_flat`, or embedded Markdown
- manifest entries include `schema_version` and `generator_version`

## 8. Parser behavior

Unchanged high-level dual-era parsing, with review hardening around containment,
output safety, incremental selection, and URL sanitization.

## 9. Privacy and URL sanitization

- Reject TLDR manage/unsubscribe/preferences/account/referral URLs entirely.
- Preserve ordinary editorial query parameters including `t`, `p`, `s`, `token`,
  `uid`, and `user_id`.
- Strip subscriber-identifying params (`email`, `subscriber`, `subscriber_id`)
  so they never appear in generated artifacts.
- No network redirect resolution.

## 10. CLI commands

```bash
python3 -m tools.tldr_derive inspect
python3 -m tools.tldr_derive validate --all --strict-privacy
python3 -m tools.tldr_derive generate --all --dry-run
python3 -m tools.tldr_derive generate --changed
python3 -m tools.tldr_derive generate --all
python3 -m tools.tldr_derive generate --source "TLDR AI/article_01-01-2026.md"
python3 -m tools.tldr_derive estimate --all
```

### Validation terminology

`processed_count` means sources parsed **without raising an exception**.
It is **not** `parse_status == "complete"`. Use `parse_status_counts` for
complete/partial/failed totals. (`ok_count` was removed.)

### Manifest safety

- `generate --all` with any source exception: does **not** replace an existing
  manifest with a partial full replace; returns non-zero; keeps successful issue
  JSON writes.
- `generate --changed` with failures: merges only successful updates; failed
  sources remain eligible for retry.

## 11. Tests added

`tests_derive/test_derive.py` — **41** unittest cases, including review coverage for:

- version-aware `--changed` (hash / missing JSON / schema / generator)
- sibling path-prefix containment regression
- rejection of `TLDR/generated` and `TLDR AI/generated` output roots
- editorial query-parameter preservation
- injected exception failure isolation + `--all`/`--changed` manifest safety
- `processed_count` validation reporting

## 12. Exact commands executed

```bash
PYTHONPATH=. python3 -m unittest tests_derive.test_derive
PYTHONPATH=. python3 -m tools.tldr_derive validate --all --strict-privacy
PYTHONPATH=. python3 -m tools.tldr_derive estimate --all
PYTHONPATH=. python3 -m tools.tldr_derive generate --source "TLDR/article_15-07-2026.md" --output /tmp/tldr_idem2
# second identical run + diff => idempotent
```

Not executed: `script.py`, `test_remove.py`, `tests/test_decode.py`, archives IMAP
scripts, `automation.sh`, `push_script.sh`.

## 13. Test results and exit codes

| Command | Exit code | Result |
|---------|----------:|--------|
| `python3 -m unittest tests_derive.test_derive` | 0 | Ran **41** tests, OK |
| `validate --all --strict-privacy` | 0 | 5928 processed / 0 errors / 0 privacy hits |
| `estimate --all` | 0 | size report emitted |
| idempotent double generate + `diff -ru` | 0 | no differences |

## 14. Full-corpus validation results

- `source_count`: 5928
- `processed_count`: 5928  *(parsed without exception; not complete-count)*
- `error_count`: 0
- `privacy_hits`: `[]`

## 15. Parse complete/partial/failed counts

| Status | Count |
|--------|------:|
| complete | 5597 |
| partial | 327 |
| failed | 4 |

## 16. Format-family counts

| Family | Count |
|--------|------:|
| links_block | 5176 |
| inline_url | 751 |
| unknown | 1 |

## 17. Size estimates

| Metric | Value |
|--------|------:|
| issue_count | 5928 |
| estimated_total_json_bytes | 74,839,044 |
| average_bytes_per_issue | 12,624.67 |
| median_bytes_per_issue | 12,578.5 |
| p95_bytes_per_issue | 16,187 |
| max_bytes_per_issue | 20,988 |
| estimated_manifest_size_bytes | 1,541,360 |
| estimated_annual_repository_growth_bytes | 23,772,240 |

## 18. Idempotency evidence

Double generation of `TLDR/article_15-07-2026.md` into `/tmp/tldr_idem2` followed by
`diff -ru` produced no differences (`IDEMPOTENT_OK`).

## 19. Source immutability evidence

- count **5928** matches baseline
- combined hash
  `69249e843a15ba4bd0697598e76320ede0b2fb16347b570bbf77f392c7dd7787` matches baseline

## 20. Production-file immutability evidence

`git hash-object` matched base commit objects for:

- `script.py`
- `automation.sh`
- `push_script.sh`
- `cronjob`
- `Pipfile.lock`

## 21. Privacy verification

- corpus validate `--strict-privacy`: **0** hits, exit 0
- expected samples remain free of unsubscribe/manage subscriber tokens

## 22. Sample generated outputs

Committed under `tests_derive/expected/` (regenerated for generator `0.1.1`).

## 23. Known parser limitations

- Some 2023 inline-era issues remain `partial` (often `missing_inline_url`)
- A few early Crypto issues remain `failed`
- Section detection is conservative
- Tracking short-links are preserved as-is (no redirect resolution)
- Editorial article text may mention the word “unsubscribe” in third-party article
  URLs; that is not treated as a TLDR management link

## 24. Risks remaining

- Full backfill would add ~75MB derived JSON if committed later
- Parser quality on edge historical mail can still improve without schema breaks

## 25. Backfill proposal, not executed

```bash
python3 -m tools.tldr_derive generate --all --output generated
```

**Not executed / not committed in this PR.**

## 26. Daily integration proposal, not activated

Future post-push `generate --changed` remains a separate approval. **Not activated.**

## 27. Dependency changes

- No runtime dependency added (stdlib only)
- `Pipfile.lock` unchanged
- CI uses Actions `checkout` / `setup-python` only

## 28. Complete git diff summary

Branch changes are limited to derive tooling, safe tests, docs, gitignore,
`generated/.gitkeep`, and `.github/workflows/derive-ci.yml`.

No sealed production or newsletter source content changes.

## 29. Review checklist

- [x] Version-aware `--changed` (hash / missing JSON / schema / generator)
- [x] `relative_to` source containment + sibling-prefix regression test
- [x] Output roots inside `TLDR*` rejected before writes
- [x] Editorial query params preserved; TLDR manage/unsub removed
- [x] Real injected-failure isolation + manifest safety for `--all` / `--changed`
- [x] `processed_count` terminology + warning-code distribution
- [x] Safe GitHub Actions workflow added
- [x] 41 unit tests pass
- [x] Full-corpus strict privacy validation pass
- [x] No backfill committed
- [x] Draft PR remains draft (not marked ready; not merged)

## 30. Warning-code distribution

### Corpus-wide warning occurrences

| Code | Count |
|------|------:|
| footer_truncated | 5927 |
| missing_inline_url | 515 |
| missing_reference_number | 16 |
| skipped_private_or_invalid_url | 3 |
| unknown_format | 1 |

### Among the 327 `partial` issues (unique codes per issue)

| Code | Partial issues containing code |
|------|-------------------------------:|
| footer_truncated | 327 |
| missing_inline_url | 313 |
| missing_reference_number | 14 |

## 31. CI workflow

`.github/workflows/derive-ci.yml` runs only:

1. `python3 -m unittest tests_derive.test_derive`
2. `python3 -m tools.tldr_derive validate --all --strict-privacy`

It never executes production, IMAP, archive, or legacy diagnostic scripts.
