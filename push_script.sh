#!/usr/bin/env bash
# Validate, commit approved newsletter + generated paths, rebase, and push.
# Safe to invoke every minute during the scheduled hours.
#
# Empty staging does NOT exit early: pull/rebase still runs so unpushed local
# commits and origin/main advances are handled.

set -Eeuo pipefail

REPO_ROOT="${REPO_ROOT:-/home/galois/bots/tldr_news}"
PYTHON_BIN="${PYTHON_BIN:-/home/galois/.local/share/virtualenvs/tldr_news-_ykhbpHM/bin/python3}"
LOCK_FILE="${LOCK_FILE:-/tmp/tldr_news_pipeline.lock}"
LOG_DIR="${LOG_DIR:-${REPO_ROOT}/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/push.log}"
SUCCESS_MARKER="${SUCCESS_MARKER:-${LOG_DIR}/last_push_success}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"

SCRIPT_NAME="$(basename "$0")"

mkdir -p "${LOG_DIR}"

# shellcheck source=scripts/pipeline_lib.sh
source "${REPO_ROOT}/scripts/pipeline_lib.sh"

enable_pipeline_logging
trap on_err ERR

if ! acquire_pipeline_lock; then
  log "lock held by another pipeline process; exiting successfully"
  exit 0
fi

cd "${REPO_ROOT}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  log "PYTHON_BIN is not executable: ${PYTHON_BIN}"
  exit 1
fi

require_main_branch

log "start sync+validate+push REPO_ROOT=${REPO_ROOT}"

# Recovery / idempotency before considering a commit.
run_generate_changed
log "initial generate --changed completed"

# Normalized strict validation always precedes optional external publication.
run_source_and_editorial_publication

stage_approved_sources
stage_generated
stage_editorial
run_raw_source_privacy
log "staged raw-source privacy gate passed"

if git diff --cached --quiet; then
  log "no staged changes before rebase"
else
  log "staged changes present; running pre-commit validation"
  run_validate
  log "validate --all --strict-privacy passed"
  run_consistency
  log "structural consistency check passed"
  run_editorial_consistency
  log "editorial consistency check passed before commit"

  pre_commit_out="$(run_generate_changed)"
  printf '%s\n' "${pre_commit_out}"
  if ! printf '%s\n' "${pre_commit_out}" | require_generate_clean; then
    log "generate --changed is not clean before commit; aborting"
    exit 1
  fi
  log "changed_clean before commit"

  stage_generated
  stage_editorial
  run_raw_source_privacy
  log "pre-commit raw-source privacy gate passed"
  msg="Daily TLDR update $(date -u +'%Y-%m-%d %H:%M') UTC"
  git commit -m "${msg}"
  log "committed: ${msg}"
fi

if ! git pull --rebase "${REMOTE}" "${BRANCH}"; then
  log "ERROR: git pull --rebase failed; local commit(s) preserved for manual recovery"
  log "Do not force-push or hard-reset. Resolve rebase conflict manually, then push."
  exit 1
fi
log "pull --rebase completed"

# Post-rebase correctness: never push without re-checking derived data.
run_generate_changed
log "post-rebase generate --changed completed"
run_source_and_editorial_publication
log "post-rebase validate passed"
log "post-rebase normalized + editorial checks passed"

post_out="$(run_generate_changed)"
printf '%s\n' "${post_out}"
if ! printf '%s\n' "${post_out}" | require_generate_clean; then
  log "post-rebase generate --changed is not clean; aborting before push"
  exit 1
fi
log "changed_clean after rebase"

stage_generated
stage_editorial
if ! git diff --cached --quiet; then
  run_raw_source_privacy
  log "post-rebase pre-commit raw-source privacy gate passed"
  sync_msg="Daily TLDR generated sync $(date -u +'%Y-%m-%d %H:%M') UTC"
  git commit -m "${sync_msg}"
  log "committed post-rebase generated sync: ${sync_msg}"
else
  log "no post-rebase generated changes to commit"
fi

ahead="$(git rev-list --count "${REMOTE}/${BRANCH}..HEAD")"
if [[ "${ahead}" -gt 0 ]]; then
  git push "${REMOTE}" "${BRANCH}"
  log "pushed ${ahead} commit(s) to ${REMOTE}/${BRANCH}"
else
  log "nothing to push"
fi

git fetch --quiet "${REMOTE}" "${BRANCH}"
"${PYTHON_BIN}" script.py --ack
log "durably published mail acknowledged"

printf '%s\n' "$(ts_utc)" > "${SUCCESS_MARKER}"
log "success marker written: ${SUCCESS_MARKER}"
log "done"
exit 0
