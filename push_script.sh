#!/usr/bin/env bash
# Validate, commit approved newsletter + generated paths, rebase, and push.
# Safe to invoke every minute during the scheduled hours.

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
# shellcheck source=scripts/pipeline_lib.sh
source "${REPO_ROOT}/scripts/pipeline_lib.sh"

trap on_err ERR

mkdir -p "${LOG_DIR}"

if ! acquire_pipeline_lock; then
  log "lock held by another pipeline process; exiting successfully"
  exit 0
fi

cd "${REPO_ROOT}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  log "PYTHON_BIN is not executable: ${PYTHON_BIN}"
  exit 1
fi

log "start sync+validate+push REPO_ROOT=${REPO_ROOT}"

# Recovery / idempotency: ensure derived data matches any new Markdown.
gen_out="$("${PYTHON_BIN}" -m tools.tldr_derive generate --changed --output generated)"
printf '%s\n' "${gen_out}" | tee -a "${LOG_FILE}" >/dev/null
printf '%s\n' "${gen_out}"
log "initial generate --changed completed"

# Stage only approved newsletter directories and generated artifacts.
while IFS= read -r -d '' directory; do
  git add -A -- "${directory}"
done < <(
  find "${REPO_ROOT}" -mindepth 1 -maxdepth 1 -type d \
    \( -name 'TLDR' -o -name 'TLDR *' \) -print0
)

mkdir -p generated/issues
if [[ -e generated/manifest.json ]]; then
  git add -A -- generated/manifest.json
fi
if [[ -d generated/issues ]]; then
  git add -A -- generated/issues
fi

if git diff --cached --quiet; then
  log "nothing to commit"
  exit 0
fi

log "staged changes present; running validation"

"${PYTHON_BIN}" -m tools.tldr_derive validate --all --strict-privacy
log "validate --all --strict-privacy passed"

"${PYTHON_BIN}" -m tools.check_generated_consistency --output generated
log "structural consistency check passed"

final_out="$("${PYTHON_BIN}" -m tools.tldr_derive generate --changed --output generated)"
printf '%s\n' "${final_out}" | tee -a "${LOG_FILE}" >/dev/null
printf '%s\n' "${final_out}"

# Require a clean --changed pass before commit (JSON summary on stdout).
if ! printf '%s\n' "${final_out}" | "${PYTHON_BIN}" -c '
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
'; then
  log "final generate --changed is not clean; aborting before commit"
  exit 1
fi
log "changed_clean"

# Re-stage generated paths in case the final generate touched anything (it should not).
if [[ -e generated/manifest.json ]]; then
  git add -A -- generated/manifest.json
fi
if [[ -d generated/issues ]]; then
  git add -A -- generated/issues
fi

msg="Daily TLDR update $(date -u +'%Y-%m-%d %H:%M') UTC"
git commit -m "${msg}"
log "committed: ${msg}"

if ! git pull --rebase "${REMOTE}" "${BRANCH}"; then
  log "ERROR: git pull --rebase failed; local commit preserved for manual recovery"
  log "Do not force-push or hard-reset. Resolve rebase conflict manually, then push."
  exit 1
fi

git push "${REMOTE}" "${BRANCH}"
log "pushed to ${REMOTE}/${BRANCH}"

printf '%s\n' "$(ts_utc)" > "${SUCCESS_MARKER}"
log "success marker written: ${SUCCESS_MARKER}"
log "done"
exit 0
