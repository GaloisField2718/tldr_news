#!/usr/bin/env bash
# Shared helpers for automation.sh / push_script.sh (sourced).
# Logging + non-blocking exclusive lock via flock(1) (required).

ts_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  # Whole-script stdout/stderr is already tee'd to LOG_FILE; print once.
  printf '%s [%s] %s\n' "$(ts_utc)" "${SCRIPT_NAME}" "$*"
}

on_err() {
  local ec=$?
  local line="${BASH_LINENO[0]:-unknown}"
  local cmd="${BASH_COMMAND:-unknown}"
  log "ERROR script=${SCRIPT_NAME} line=${line} exit=${ec} cmd=${cmd}"
}

# Redirect this shell's stdout/stderr through tee into LOG_FILE (append).
# Idempotent across nested sourcing / re-entry.
enable_pipeline_logging() {
  mkdir -p "$(dirname "${LOG_FILE}")"
  if [[ "${TLDR_PIPELINE_DISABLE_TEE:-0}" == "1" ]]; then
    return 0
  fi
  if [[ "${TLDR_PIPELINE_TEE_ACTIVE:-0}" == "1" ]]; then
    return 0
  fi
  export TLDR_PIPELINE_TEE_ACTIVE=1
  exec > >(tee -a "${LOG_FILE}") 2>&1
}

# Acquire non-blocking exclusive lock on LOCK_FILE using FD 9.
# Returns 0 on success, 1 if lock is busy. Exits non-zero if flock missing.
acquire_pipeline_lock() {
  if ! command -v flock >/dev/null 2>&1; then
    log "ERROR: flock is required but was not found in PATH"
    log "Install util-linux flock on the host (expected on the Linux VPS)."
    exit 1
  fi
  exec 9>"${LOCK_FILE}"
  if flock -n 9; then
    return 0
  fi
  return 1
}

require_main_branch() {
  local head
  if ! head="$(git symbolic-ref --short HEAD 2>/dev/null)"; then
    log "ERROR: detached HEAD or invalid git checkout; expected branch main"
    exit 1
  fi
  if [[ "${head}" != "main" ]]; then
    log "ERROR: expected branch main, found '${head}'; refusing git work"
    exit 1
  fi
  log "on branch main"
}

stage_approved_sources() {
  while IFS= read -r -d '' directory; do
    git add -A -- "${directory}"
  done < <(
    find "${REPO_ROOT}" -mindepth 1 -maxdepth 1 -type d \
      \( -name 'TLDR' -o -name 'TLDR *' \) -print0
  )
}

stage_generated() {
  mkdir -p generated/issues
  if [[ -e generated/manifest.json ]]; then
    git add -A -- generated/manifest.json
  fi
  if [[ -d generated/issues ]]; then
    git add -A -- generated/issues
  fi
}

stage_editorial() {
  # Deliberately stage JSON contracts only; never binaries or arbitrary files.
  if [[ -f generated/editorial/manifest.json ]]; then
    git add -- generated/editorial/manifest.json
  fi
  if [[ -d generated/editorial ]]; then
    while IFS= read -r -d '' artifact; do
      git add -- "${artifact}"
    done < <(find generated/editorial -mindepth 2 -maxdepth 2 -type f -name '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json' -print0)
  fi
}

run_editorial_latest() {
  "${PYTHON_BIN}" -m tools.tldr_editorial generate --latest --output generated/editorial
}

run_editorial_consistency() {
  "${PYTHON_BIN}" -m tools.tldr_editorial validate --all --output generated/editorial
}

run_generate_changed() {
  "${PYTHON_BIN}" -m tools.tldr_derive generate --changed --output generated
}

require_generate_clean() {
  # Reads generate JSON summary from stdin.
  "${PYTHON_BIN}" -c '
import json, sys
doc = json.loads(sys.stdin.read())
selected = doc.get("selected")
written = doc.get("written")
failures = doc.get("failures")
if selected != 0 or written != 0 or failures not in ([], None):
    print(
        f"changed_not_clean selected={selected} written={written} failures={failures}",
        file=sys.stderr,
    )
    sys.exit(1)
print("changed_clean")
'
}

run_validate() {
  "${PYTHON_BIN}" -m tools.tldr_derive validate --all --strict-privacy
}

run_consistency() {
  "${PYTHON_BIN}" -m tools.check_generated_consistency --output generated
}

run_source_and_editorial_publication() {
  # Live editorial work is strictly after normalized validation. Provider/storage
  # failures are represented by valid fallback artifacts and must not lose mail.
  run_validate
  log "validate --all --strict-privacy passed"
  run_consistency
  log "normalized structural consistency check passed"
  # Expected OpenRouter/image/R2 failures are serialized by the generator and
  # return zero. A non-zero result is internal/structural and must block push.
  run_editorial_latest
  log "editorial latest completed"
  run_editorial_consistency
  log "editorial structural consistency check passed"
}
