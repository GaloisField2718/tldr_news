# Daily TLDR ingestion pipeline

Operations guide for the VPS checkout at `/home/galois/bots/tldr_news`.

## Schedule

The live crontab runs jobs **every minute during specific hours**:

| Hour | Script | Purpose |
|------|--------|---------|
| 10 | `automation.sh` | IMAP ingestion → `generate --changed` |
| 17 | `push_script.sh` | recovery generate → validate → commit → rebase/push |
| 23 | `automation.sh` | second ingestion window |
| 00 | `push_script.sh` | second push window |

Because `* 10 * * *` means every minute of hour 10, scripts are idempotent and
share a non-blocking exclusive lock (`/tmp/tldr_news_pipeline.lock`) via
`flock(1)` when available, or an `fcntl` fallback on hosts without util-linux.
If the lock is held, the later invocation exits 0 without work.

Tracked copy of the crontab: repository file `cronjob` (documentation only;
do not auto-install).

## Processing flow

```text
automation.sh
  flock
  -> python3 script.py                  # IMAP ingestion (unchanged)
  -> python3 -m tools.tldr_derive generate --changed --output generated
  -> logs/last_automation_success
  (no git)

push_script.sh
  flock
  -> generate --changed                 # recovery / idempotency
  -> git add approved TLDR* dirs + generated/manifest.json + generated/issues
  -> if nothing staged: exit 0
  -> validate --all --strict-privacy
  -> python3 -m tools.check_generated_consistency --output generated
  -> generate --changed again; require selected=0, written=0, failures=[]
  -> git commit
  -> git pull --rebase origin main
  -> git push origin main
  -> logs/last_push_success
```

## Constants

```text
REPO_ROOT=/home/galois/bots/tldr_news
PYTHON_BIN=/home/galois/.local/share/virtualenvs/tldr_news-_ykhbpHM/bin/python3
LOCK_FILE=/tmp/tldr_news_pipeline.lock
```

Override via environment for offline tests only.

## Logs and success markers

| Path | Meaning |
|------|---------|
| `logs/automation.log` | append-only automation log |
| `logs/push.log` | append-only push log |
| `logs/last_automation_success` | UTC timestamp of last successful automation |
| `logs/last_push_success` | UTC timestamp of last successful push |

`logs/` is gitignored.

## Inspection commands

```bash
cd /home/galois/bots/tldr_news
PYTHON_BIN=/home/galois/.local/share/virtualenvs/tldr_news-_ykhbpHM/bin/python3

tail -n 200 logs/automation.log
tail -n 200 logs/push.log
cat logs/last_automation_success
cat logs/last_push_success
git status --short
git log -n 5 --oneline
"$PYTHON_BIN" -m tools.tldr_derive generate --changed --output generated
"$PYTHON_BIN" -m tools.tldr_derive validate --all --strict-privacy
```

## Verify latest Markdown and JSON correspond

```bash
# After a successful day, --changed must be a no-op:
"$PYTHON_BIN" -m tools.tldr_derive generate --changed --output generated
# Expect selected=0, written=0, failures=[]

# Spot-check one new source:
ls -lt TLDR*/article_*.md | head
ls -lt generated/issues/*/*/*.json | head
```

## Manual recovery after a rebase conflict

`push_script.sh` commits **before** `git pull --rebase`. On rebase failure it
exits non-zero, does **not** force-push, and does **not** hard-reset.

```bash
cd /home/galois/bots/tldr_news
git status
# Inspect conflicted files, resolve, then:
git add <resolved-paths>
git rebase --continue
# Or abort the rebase only if you intentionally discard the rebase attempt
# (the local daily commit remains reachable via reflog if needed):
# git rebase --abort
git push origin main
```

Never run `git push --force` or `git reset --hard` as part of recovery for this
pipeline.

## Deployment (VPS)

1. Merge/deploy this branch to `main` on the server checkout.
2. Ensure scripts are executable: `chmod +x automation.sh push_script.sh`.
3. Confirm crontab matches `cronjob` (already live; do not blindly overwrite).
4. Watch the next hour-10 / hour-17 window via the log tails above.

## Rollback

```bash
cd /home/galois/bots/tldr_news
git checkout main
git pull --ff-only
git checkout <previous-main-sha> -- automation.sh push_script.sh cronjob
# restore previous script contents and commit/push if needed
```

Or revert the merge commit on `main` with a normal revert (no force-push).
