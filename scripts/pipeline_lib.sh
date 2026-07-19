#!/usr/bin/env bash
# Shared helpers for automation.sh / push_script.sh (sourced).
# Provides logging + non-blocking exclusive lock via flock(1) or fcntl fallback.

ts_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  printf '%s [%s] %s\n' "$(ts_utc)" "${SCRIPT_NAME}" "$*" | tee -a "${LOG_FILE}" >/dev/null
  printf '%s [%s] %s\n' "$(ts_utc)" "${SCRIPT_NAME}" "$*"
}

on_err() {
  local ec=$?
  local line="${BASH_LINENO[0]:-unknown}"
  local cmd="${BASH_COMMAND:-unknown}"
  log "ERROR script=${SCRIPT_NAME} line=${line} exit=${ec} cmd=${cmd}"
}

# Acquire non-blocking exclusive lock on LOCK_FILE using FD 9.
# Returns 0 on success, 1 if lock is busy.
acquire_pipeline_lock() {
  exec 9>"${LOCK_FILE}"

  if command -v flock >/dev/null 2>&1; then
    if flock -n 9; then
      return 0
    fi
    return 1
  fi

  # Portable fallback for hosts without util-linux flock (e.g. macOS).
  # Use system python3 (not PYTHON_BIN) so app mocks do not intercept locking.
  local sys_python
  sys_python="$(command -v python3 || true)"
  if [[ -z "${sys_python}" ]]; then
    log "flock not found and python3 unavailable for lock fallback"
    exit 1
  fi

  if "${sys_python}" - <<'PY'
import fcntl
import sys

fd = 9
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(1)
except OSError as exc:
    print(f"lock_failed: {exc}", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
PY
  then
    return 0
  else
    local ec=$?
    if [[ "${ec}" -eq 1 ]]; then
      return 1
    fi
    log "unable to acquire pipeline lock (exit=${ec})"
    exit 1
  fi
}
