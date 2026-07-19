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

## Validated web redeployment

The complete production path is:

```text
email
  -> script.py
  -> newsletter Markdown source
  -> generated JSON
  -> push_script.sh
  -> tldr_news/main
  -> GitHub Actions full-corpus validation
  -> Vercel Deploy Hook
  -> tldr-news-web build
  -> immutable tldr_news source SHA
  -> production
```

A push to `tldr_news/main` starts `.github/workflows/derive-ci.yml`. The workflow
runs all derive tests, offline pipeline tests, strict privacy validation, and
generated consistency checks before its separate `deploy-web` job can run. A
failed or cancelled validation run cannot request a deployment. Concurrency
cancels an older in-progress run for the same Git ref, so repeated main pushes
do not deploy stale validated state.

The repository Actions secret is named `VERCEL_DEPLOY_HOOK_URL`. It contains the
Vercel Deploy Hook URL for the `tldr-news-web` project and its main branch. The
URL is a credential: never print it, place it in logs, write it to a file, or
commit it. Pull request workflows validate only and never receive a deployment
request. The deployment response is parsed as JSON and only the accepted job ID
and state are logged.

The web build resolves the latest `tldr_news/main` ref to an immutable Git commit
SHA before synchronizing `generated/`. `tldr_news` remains the source of truth
for ingestion and normalized data; `tldr-news-web` remains responsible for
presentation and search.

### Manual workflow runs

From GitHub, open **Actions → derive-ci → Run workflow** on the desired ref:

- Leave **Trigger the web deployment after successful validation** disabled for
  a validation-only run (the default).
- Enable it to run validation and request a web deployment only after validation
  succeeds.

Equivalent GitHub CLI commands are:

```bash
# Validation only (default)
gh workflow run derive-ci.yml --ref main

# Validation followed by deployment
gh workflow run derive-ci.yml --ref main -f deploy_web=true
```

A manual run with deployment enabled must be used deliberately. Unit tests and
pull request CI never call the real hook.

### Revoke or replace a compromised hook

1. In the Vercel `tldr-news-web` project settings, revoke/delete the compromised
   Deploy Hook.
2. Create a replacement hook targeting the main branch.
3. Replace the `VERCEL_DEPLOY_HOOK_URL` Actions secret in the `tldr_news`
   repository settings.
4. Run a manual validation-only workflow.
5. Run a manual workflow with `deploy_web=true` and confirm that validation and
   the deployment request both succeed.

Do not put either the revoked or replacement URL in commits, issues,
documentation, command output, or workflow inputs.

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
