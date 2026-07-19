# Daily TLDR ingestion pipeline

Operations guide for the VPS checkout at `/home/galois/bots/tldr_news`.

## Schedule

The live crontab runs jobs **every minute during specific hours**:

| Hour | Script | Purpose |
|------|--------|---------|
| 10 | `automation.sh` | IMAP ingestion → `generate --changed` |
| 17 | `push_script.sh` | sync / validate / commit / rebase / push |
| 23 | `automation.sh` | second ingestion window |
| 00 | `push_script.sh` | second push window |

Because `* 10 * * *` means every minute of hour 10, scripts are idempotent and
share a non-blocking exclusive lock (`/tmp/tldr_news_pipeline.lock`) via
**`flock(1)` (required)**. If `flock` is missing the scripts fail clearly. If
the lock is held, the later invocation exits 0 without work.

Tracked copy of the crontab: repository file `cronjob` (documentation only;
do not auto-install).

## Processing flow

```text
automation.sh
  flock (required)
  -> tee stdout/stderr to logs/automation.log
  -> python3 script.py
  -> python3 -m tools.tldr_derive generate --changed --output generated
  -> logs/last_automation_success
  (no git)

push_script.sh
  flock (required)
  -> tee stdout/stderr to logs/push.log
  -> require branch == main
  -> generate --changed
  -> stage approved TLDR* dirs + generated/manifest.json + generated/issues
  -> if staged changes:
       validate --all --strict-privacy
       check_generated_consistency
       generate --changed; require selected=0 written=0 failures=[]
       commit
  -> git pull --rebase origin main
  -> post-rebase:
       generate --changed
       validate --all --strict-privacy
       check_generated_consistency
       generate --changed; require selected=0 written=0 failures=[]
       stage generated/; commit sync commit if needed
  -> if local main ahead of origin/main: git push
     else: log "nothing to push"
  -> logs/last_push_success   # even on a full no-op success
```

Empty staging does **not** skip pull/rebase/push retry. A previous local commit
left unpushed is retried on the next cron minute.

## Constants

```text
REPO_ROOT=/home/galois/bots/tldr_news
PYTHON_BIN=/home/galois/.local/share/virtualenvs/tldr_news-_ykhbpHM/bin/python3
LOCK_FILE=/tmp/tldr_news_pipeline.lock
```

Override via environment for offline tests only (`TLDR_PIPELINE_DISABLE_TEE=1`
disables process-substitution tee under unittest capture).

## Logs and success markers

| Path | Meaning |
|------|---------|
| `logs/automation.log` | append-only automation log (full stdout/stderr) |
| `logs/push.log` | append-only push log (full stdout/stderr) |
| `logs/last_automation_success` | UTC timestamp of last successful automation |
| `logs/last_push_success` | UTC timestamp of last fully successful push run |

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
"$PYTHON_BIN" -m tools.tldr_derive generate --changed --output generated
# Expect selected=0, written=0, failures=[]

ls -lt TLDR*/article_*.md | head
ls -lt generated/issues/*/*/*.json | head
```

## Manual recovery after a rebase conflict

`push_script.sh` may commit **before** `git pull --rebase`. On rebase failure it
exits non-zero, does **not** force-push, and does **not** hard-reset.

```bash
cd /home/galois/bots/tldr_news
git status
git add <resolved-paths>
git rebase --continue
git push origin main
```

Never run `git push --force` or `git reset --hard` as part of recovery for this
pipeline.

## Deployment (VPS)

1. Merge/deploy this branch to `main` on the server checkout.
2. Ensure scripts are executable: `chmod +x automation.sh push_script.sh`.
3. Confirm `flock` exists: `command -v flock`.
4. Confirm crontab matches `cronjob` (already live; do not auto-install).
5. Watch the next hour-10 / hour-17 window via the log tails above.

## Rollback

```bash
cd /home/galois/bots/tldr_news
git checkout main
git pull --ff-only
git checkout <previous-main-sha> -- automation.sh push_script.sh cronjob scripts/pipeline_lib.sh
```

Or revert the merge commit on `main` with a normal revert (no force-push).
