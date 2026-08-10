#!/usr/bin/env bash
# Resumable Daily Index podcast scheduler entrypoint.
# Safe to invoke repeatedly: missing source dates are clean skips and published dates are no-ops.

set -Eeuo pipefail

REPO_ROOT="${REPO_ROOT:-/home/galois/bots/tldr_news}"
PIPENV_BIN="${PIPENV_BIN:-/home/galois/.local/bin/pipenv}"
LOCK_FILE="${LOCK_FILE:-/tmp/tldr_news_pipeline.lock}"
LOG_DIR="${LOG_DIR:-/home/galois/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/tldr-podcast.log}"
SUCCESS_MARKER="${SUCCESS_MARKER:-${LOG_DIR}/last_podcast_success}"
TARGET_DATE="${TARGET_DATE:-$(date -u +%F)}"
SCRIPT_NAME="$(basename "$0")"

mkdir -p "${LOG_DIR}"
# shellcheck source=pipeline_lib.sh
source "${REPO_ROOT}/scripts/pipeline_lib.sh"
enable_pipeline_logging

report_error() {
  local ec=$?
  local line="${BASH_LINENO[0]:-unknown}"
  local cmd="${BASH_COMMAND:-unknown}"
  log "ERROR target_date=${TARGET_DATE} line=${line} exit=${ec} cmd=${cmd}"
  logger -t tldr-podcast "generation failed date=${TARGET_DATE} exit=${ec}" 2>/dev/null || true
  exit "${ec}"
}
trap report_error ERR

if ! acquire_pipeline_lock; then
  log "scheduler lock held; another podcast run is active; exiting successfully"
  exit 0
fi

cd "${REPO_ROOT}"
source_path="generated/editorial/${TARGET_DATE:0:4}/${TARGET_DATE}.json"
artifact_path="generated/podcast/${TARGET_DATE:0:4}/${TARGET_DATE}.json"

log "start target_date=${TARGET_DATE}"
if [[ -f "${artifact_path}" ]]; then
  # Publication may have succeeded immediately before the process was interrupted
  # while committing/pushing the JSON artifact. Recover that durable hand-off
  # without re-entering the paid generation path.
  log "published artifact exists; syncing artifact only=${artifact_path}"
  git add -- "${artifact_path}"
  if ! git diff --cached --quiet -- "${artifact_path}"; then
    git commit --only -- "${artifact_path}" -m "Publish bilingual Daily podcast for ${TARGET_DATE}"
    log "committed existing podcast artifact"
  fi
  git push
  log "existing podcast artifact synchronized"
  exit 0
fi
if [[ ! -f "${source_path}" ]]; then
  log "no Daily editorial source for target date; clean skip source=${source_path}"
  exit 0
fi
if [[ ! -x "${PIPENV_BIN}" ]]; then
  log "PIPENV_BIN is not executable: ${PIPENV_BIN}"
  exit 1
fi

"${PIPENV_BIN}" run python -m tools.tldr_podcast run-daily --date "${TARGET_DATE}" --publish
printf '%s date=%s\n' "$(ts_utc)" "${TARGET_DATE}" > "${SUCCESS_MARKER}"
log "published successfully; success marker=${SUCCESS_MARKER}"
