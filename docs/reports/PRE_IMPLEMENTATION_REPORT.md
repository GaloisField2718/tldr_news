# Pre-implementation report

> Archived copy of the approved pre-implementation analysis for PR1.
> Base inspection commit: `db370327ee0f8a787f0a4136e5f8dc37edfb62db`.

## 1. Executive summary

The repository is a stable IMAP→Markdown→git pipeline with **5,928** approved TLDR
Markdown issues (plus excluded pollution). PR1 must not touch ingestion. The approved
minimal architecture is: immutable Markdown sources + offline stdlib derivation into
per-issue JSON + manifest/search-ready metadata, without cleaned Markdown duplicates
and without production cron integration.

## 2–18. Approved analysis

The full inspection findings (pipeline inventory, corpus statistics, architecture
comparison, safety classification, and implementation plan) were reviewed and approved
in the pre-implementation phase. Key frozen facts:

- Branch/commit inspected: `main` @ `db370327ee0f8a787f0a4136e5f8dc37edfb62db`
- Production sealed files: `script.py`, `automation.sh`, `push_script.sh`, `cronjob`
- Unsafe never-run scripts: `test_remove.py`, `tests/test_decode.py`, archives IMAP scripts
- Format families: `inline_url` (pre-~2023-10-30) and `links_block` (after)
- Recommended architecture: derived per-issue JSON + thin global manifest (no cleaned MD copies)

## Approved amendments for PR1

These amendments override earlier draft-contract details:

1. **Do not include `generated_at`** in deterministic issue outputs.
2. **Do not include `url_raw`.**
3. **Do not include `articles_flat`.**
4. **Do not embed raw Markdown** in derived documents.
5. **`source_path` is traceability metadata only.**
6. **Never expose** subscription-management or unsubscribe URLs.
7. Use **`null` consistently** for unresolved optional values.
8. Document **1-based** `sections[].order` and `articles[].order`.
9. Output default directory: **`generated/`** with layout
   `issues/{sector_slug}/{YYYY}/{YYYY-MM-DD}.json`.
10. Stdlib-only module under `tools/tldr_derive`, runnable as
    `python3 -m tools.tldr_derive`.
11. Safe tests live in **`tests_derive/`**, not mixed with legacy diagnostics.
12. PR1 must **not** commit the full historical backfill.
13. No IMAP, no `.env` reads, no network, no runtime dependency additions.
14. Structured warnings: `{code, message, line}` with `line` nullable.

## PR1 scope reminder

Implement only the isolated derivation foundation, docs, fixtures/tests, and
verification evidence. Do not modify sealed production files or newsletter Markdown.
