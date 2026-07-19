#!/usr/bin/env bash
# Daily IMAP ingestion + derived-data sync (no git commit/push).
# Safe to invoke every minute during the scheduled hours.

set -Eeuo pipefail

REPO_ROOT="${REPO_ROOT:-/home/galois/bots/tldr_news}"
PYTHON_BIN="${PYTHON_BIN:-/home/galois/.local/share/virtualenvs/tldr_news-_ykhbpHM/bin/python3}"
LOCK_FILE="${LOCK_FILE:-/tmp/tldr_news_pipeline.lock}"
LOG_DIR="${LOG_DIR:-${REPO_ROOT}/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/automation.log}"
SUCCESS_MARKER="${SUCCESS_MARKER:-${LOG_DIR}/last_automation_success}"

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

log "start ingestion+generate REPO_ROOT=${REPO_ROOT}"

"${PYTHON_BIN}" script.py
log "script.py completed successfully"

run_generate_changed
log "generate --changed completed"

printf '%s\n' "$(ts_utc)" > "${SUCCESS_MARKER}"
log "success marker written: ${SUCCESS_MARKER}"
log "done"
exit 0
