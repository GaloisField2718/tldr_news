"""Offline tests for daily automation.sh / push_script.sh orchestration.

Does not execute the real script.py, read .env, or contact IMAP/network remotes
outside a temporary local git bare repository.

Provides a PATH-local flock(1) shim so macOS/dev hosts without util-linux can
still exercise lock behavior offline. CI (Ubuntu) uses real flock.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from tools.check_generated_consistency import check_generated
from tools.tldr_derive import GENERATOR_VERSION, SCHEMA_VERSION

REPO = Path(__file__).resolve().parents[1]
AUTOMATION = REPO / "automation.sh"
PUSH = REPO / "push_script.sh"
PIPELINE_LIB = REPO / "scripts" / "pipeline_lib.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


FLOCK_SHIM = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    \"\"\"Minimal flock(1) shim for offline tests (flock -n FD).\"\"\"
    import fcntl
    import sys

    args = sys.argv[1:]
    nonblock = False
    if args and args[0] == "-n":
        nonblock = True
        args = args[1:]
    if len(args) != 1 or not args[0].isdigit():
        print("flock shim supports only: flock [-n] FD", file=sys.stderr)
        sys.exit(64)
    fd = int(args[0])
    flags = fcntl.LOCK_EX
    if nonblock:
        flags |= fcntl.LOCK_NB
    try:
        fcntl.flock(fd, flags)
    except BlockingIOError:
        sys.exit(1)
    sys.exit(0)
    """
)


class ScriptStaticGuards(unittest.TestCase):
    def test_bash_syntax(self) -> None:
        for script in (AUTOMATION, PUSH, PIPELINE_LIB):
            proc = subprocess.run(
                ["bash", "-n", str(script)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_no_dangerous_git_or_activate(self) -> None:
        for script in (AUTOMATION, PUSH):
            text = script.read_text(encoding="utf-8")
            self.assertNotIn("git add .", text)
            self.assertNotIn("git add -A .", text)
            self.assertNotIn("push --force", text)
            self.assertNotIn("push -f", text)
            self.assertNotIn("reset --hard", text)
            self.assertNotIn("commit --amend", text)
            self.assertNotIn("source activate", text)
            self.assertTrue(text.startswith("#!/usr/bin/env bash"))
            self.assertIn("set -Eeuo pipefail", text)
            self.assertIn("acquire_pipeline_lock", text)
        lib = PIPELINE_LIB.read_text(encoding="utf-8")
        self.assertIn("flock -n", lib)
        self.assertNotIn("fcntl.flock", lib)
        self.assertIn("flock is required", lib)
        push = PUSH.read_text(encoding="utf-8")
        self.assertIn("require_main_branch", push)
        self.assertIn("pull --rebase", push)
        self.assertIn("nothing to push", push)
        self.assertIn("no staged changes before rebase", push)

    def test_push_stages_only_approved_paths(self) -> None:
        text = PUSH.read_text(encoding="utf-8")
        self.assertIn("stage_approved_sources", text)
        self.assertIn("stage_generated", text)
        self.assertIn("stage_editorial", text)
        self.assertIn("run_source_and_editorial_publication", text)
        self.assertNotIn("git add .", text)
        lib = PIPELINE_LIB.read_text(encoding="utf-8")
        self.assertIn("tools.tldr_editorial generate", lib)
        self.assertIn("tools.tldr_editorial validate", lib)
        self.assertNotIn("generated/editorial/images", lib)
        self.assertNotIn("if ! run_editorial_latest", lib)
        self.assertIn("run_editorial_latest\n", lib)


class ConsistencyModuleTests(unittest.TestCase):
    def test_check_passes_on_real_generated(self) -> None:
        generated = REPO / "generated"
        if not (generated / "manifest.json").is_file():
            self.skipTest("generated/ not present")
        self.assertEqual(check_generated(generated), [])


class PipelineTempRepoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tldr_pipeline_"))
        self.repo = self.tmp / "repo"
        self.bare = self.tmp / "remote.git"
        self.lock = self.tmp / "pipeline.lock"
        self.bin_dir = self.tmp / "bin"
        self.bin_dir.mkdir()
        _write_executable(self.bin_dir / "flock", FLOCK_SHIM)

        self.repo.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "pipeline-test@example.com"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Pipeline Test"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        (self.repo / "TLDR").mkdir()
        (self.repo / "TLDR" / "article_01-01-2024.md").write_text(
            "# Articles TLDR 01-01-2024\n\nHEADER ONLY\n",
            encoding="utf-8",
        )
        (self.repo / "generated" / "issues" / "tldr" / "2024").mkdir(parents=True)
        issue = {
            "issue_id": "tldr:2024-01-01",
            "schema_version": SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "source_path": "TLDR/article_01-01-2024.md",
            "parse_status": "failed",
            "format_family": "unknown",
            "sections": [],
        }
        issue_path = (
            self.repo / "generated" / "issues" / "tldr" / "2024" / "2024-01-01.json"
        )
        issue_path.write_text(json.dumps(issue), encoding="utf-8")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "issues": [
                {
                    "issue_id": "tldr:2024-01-01",
                    "sector": "TLDR",
                    "sector_slug": "tldr",
                    "date": "2024-01-01",
                    "source_path": "TLDR/article_01-01-2024.md",
                    "source_content_hash": "sha256:dead",
                    "schema_version": SCHEMA_VERSION,
                    "generator_version": GENERATOR_VERSION,
                    "format_family": "unknown",
                    "parse_status": "failed",
                    "derived_path": "issues/tldr/2024/2024-01-01.json",
                }
            ],
        }
        (self.repo / "generated" / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (self.repo / ".gitignore").write_text("logs\n.env\n", encoding="utf-8")
        (self.repo / ".env").write_text("SECRET=do-not-stage\n", encoding="utf-8")
        (self.repo / "logs").mkdir()
        (self.repo / "logs" / "noise.log").write_text("x\n", encoding="utf-8")

        shutil.copy2(AUTOMATION, self.repo / "automation.sh")
        shutil.copy2(PUSH, self.repo / "push_script.sh")
        (self.repo / "scripts").mkdir(exist_ok=True)
        shutil.copy2(PIPELINE_LIB, self.repo / "scripts" / "pipeline_lib.sh")
        (self.repo / "automation.sh").chmod(0o755)
        (self.repo / "push_script.sh").chmod(0o755)
        (self.repo / "script.py").write_text(
            "# placeholder; never executed by real IMAP\n", encoding="utf-8"
        )

        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "init", "--bare", str(self.bare)], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "remote", "add", "origin", str(self.bare)],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )

        self.mock_state = self.tmp / "mock_state.json"
        self.mock_state.write_text(
            json.dumps(
                {
                    "script_exit": 0,
                    "script_calls": 0,
                    "generate_calls": 0,
                    "validate_calls": 0,
                    "consistency_calls": 0,
                    "editorial_generate_calls": 0,
                    "editorial_validate_calls": 0,
                    "editorial_generate_exit": 7,
                    "editorial_generate_fail_on_call": 0,
                    "editorial_validate_exit": 0,
                    "editorial_status": "disabled",
                    "generate_selected": 0,
                    "generate_written": 0,
                    "validate_exit": 0,
                    "consistency_exit": 0,
                    "generate_extra_files": 0,
                }
            ),
            encoding="utf-8",
        )
        self.python_bin = self.tmp / "mock_python"
        self._write_mock_python()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_mock_python(self) -> None:
        state_path = self.mock_state
        repo = self.repo
        content = textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            STATE="{state_path}"
            REPO="{repo}"
            py_update() {{
              /usr/bin/env python3 - "$STATE" "$@" <<'PY'
            import json, sys
            path = sys.argv[1]
            key = sys.argv[2]
            delta = int(sys.argv[3]) if len(sys.argv) > 3 else 1
            doc = json.loads(open(path, encoding="utf-8").read())
            if key.endswith("_exit") or key.endswith("_selected") or key.endswith("_written") or key.endswith("_files"):
                doc[key] = delta
            else:
                doc[key] = doc.get(key, 0) + delta
            open(path, "w", encoding="utf-8").write(json.dumps(doc))
            PY
            }}
            py_get() {{
              /usr/bin/env python3 - "$STATE" "$1" <<'PY'
            import json, sys
            doc = json.loads(open(sys.argv[1], encoding="utf-8").read())
            print(doc.get(sys.argv[2], 0))
            PY
            }}

            if [[ "${{1:-}}" == "script.py" ]]; then
              py_update script_calls 1 >/dev/null
              exit "$(py_get script_exit)"
            fi

            if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "tools.tldr_derive" ]]; then
              cmd="${{3:-}}"
              if [[ "$cmd" == "generate" ]]; then
                py_update generate_calls 1 >/dev/null
                extra="$(py_get generate_extra_files)"
                if [[ "$extra" != "0" ]]; then
                  mkdir -p "$REPO/generated/issues/tldr/2024"
                  echo '{{"issue_id":"extra","schema_version":"{SCHEMA_VERSION}","generator_version":"{GENERATOR_VERSION}"}}' \
                    > "$REPO/generated/issues/tldr/2024/extra-from-generate.json"
                  # one-shot
                  py_update generate_extra_files 0 >/dev/null
                fi
                selected="$(py_get generate_selected)"
                written="$(py_get generate_written)"
                /usr/bin/env python3 -c "import json; print(json.dumps({{'selected': int('$selected'), 'written': int('$written'), 'skipped': 0, 'failures': [], 'dry_run': False}}))"
                exit 0
              fi
              if [[ "$cmd" == "validate" ]]; then
                py_update validate_calls 1 >/dev/null
                exit "$(py_get validate_exit)"
              fi
            fi

            if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "tools.check_generated_consistency" ]]; then
              py_update consistency_calls 1 >/dev/null
              exit "$(py_get consistency_exit)"
            fi

            if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "tools.tldr_editorial" ]]; then
              if [[ "${{3:-}}" == "generate" ]]; then
                py_update editorial_generate_calls 1 >/dev/null
                calls="$(py_get editorial_generate_calls)"
                fail_on="$(py_get editorial_generate_fail_on_call)"
                if [[ "$fail_on" != "0" && "$calls" == "$fail_on" ]]; then
                  exit "$(py_get editorial_generate_exit)"
                fi
                status="$(py_get editorial_status)"
                echo "{{\"status\":\"$status\",\"network_calls\":1,\"r2_calls\":0,\"written\":true}}"
                exit 0
              elif [[ "${{3:-}}" == "validate" ]]; then
                py_update editorial_validate_calls 1 >/dev/null
                exit "$(py_get editorial_validate_exit)"
              else
                exit 90
              fi
            fi

            if [[ "${{1:-}}" == "-c" ]]; then
              shift
              exec /usr/bin/env python3 -c "$@"
            fi

            echo "unexpected mock_python args: $*" >&2
            exit 90
            """
        )
        _write_executable(self.python_bin, content)

    def _state(self) -> dict:
        return json.loads(self.mock_state.read_text(encoding="utf-8"))

    def _set_state(self, **kwargs: object) -> None:
        doc = self._state()
        doc.update(kwargs)
        self.mock_state.write_text(json.dumps(doc), encoding="utf-8")

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"
        env.update(
            {
                "REPO_ROOT": str(self.repo),
                "PYTHON_BIN": str(self.python_bin),
                "LOCK_FILE": str(self.lock),
                "LOG_DIR": str(self.repo / "logs"),
                "REMOTE": "origin",
                "BRANCH": "main",
                "PYTHONPATH": str(REPO),
                "TLDR_PIPELINE_TEE_ACTIVE": "0",
                "TLDR_PIPELINE_DISABLE_TEE": "1",
            }
        )
        return env

    def _run(self, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.repo / script)],
            cwd=self.repo,
            env=self._env(),
            check=False,
            capture_output=True,
            text=True,
        )

    def _rev(self) -> str:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _remote_rev(self) -> str:
        return subprocess.run(
            ["git", "--git-dir", str(self.bare), "rev-parse", "main"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _plant_remote_only_commit(
        self, relative_path: str, content: str, message: str
    ) -> str:
        """Push a commit to origin/main, then reset local main behind it.

        Avoids a second clone (unreliable push-to-bare on some CI hosts).
        """
        before = self._rev()
        path = self.repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(
            ["git", "add", "--", relative_path],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        push = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=self.repo,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(push.returncode, 0, msg=push.stderr + push.stdout)
        remote_tip = self._rev()
        subprocess.run(
            ["git", "reset", "--hard", before],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        self.assertNotEqual(self._rev(), remote_tip)
        self.assertEqual(remote_tip, self._remote_rev())
        return remote_tip

    def test_lock_contention_exits_cleanly(self) -> None:
        holder = subprocess.Popen(
            [
                "bash",
                "-c",
                f'export PATH="{self.bin_dir}:$PATH"; '
                f'exec 9>"{self.lock}"; flock -n 9 || exit 1; sleep 8',
            ]
        )
        try:
            time.sleep(0.3)
            proc = self._run("automation.sh")
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
            self.assertIn("lock held", proc.stdout)
            self.assertEqual(self._state()["script_calls"], 0)
        finally:
            holder.terminate()
            holder.wait(timeout=5)

    def test_automation_stops_when_script_fails(self) -> None:
        self._set_state(script_exit=7)
        proc = self._run("automation.sh")
        self.assertNotEqual(proc.returncode, 0)
        st = self._state()
        self.assertEqual(st["script_calls"], 1)
        self.assertEqual(st["generate_calls"], 0)
        self.assertFalse((self.repo / "logs" / "last_automation_success").exists())

    def test_automation_accepts_selected_zero(self) -> None:
        self._set_state(script_exit=0, generate_selected=0, generate_written=0)
        proc = self._run("automation.sh")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        st = self._state()
        self.assertEqual(st["script_calls"], 1)
        self.assertGreaterEqual(st["generate_calls"], 1)
        self.assertTrue((self.repo / "logs" / "last_automation_success").is_file())

    def test_push_noop_updates_success_marker(self) -> None:
        marker = self.repo / "logs" / "last_push_success"
        self.assertFalse(marker.exists())
        self._set_state(validate_exit=0, consistency_exit=0, generate_selected=0)
        proc = self._run("push_script.sh")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        self.assertIn("nothing to push", proc.stdout)
        self.assertTrue(marker.is_file())
        self.assertGreaterEqual(self._state()["validate_calls"], 1)

    def test_push_does_not_stage_logs_or_env(self) -> None:
        (self.repo / "TLDR" / "article_02-01-2024.md").write_text(
            "# Articles TLDR 02-01-2024\n\nNEW\n", encoding="utf-8"
        )
        (self.repo / ".env").write_text("SECRET=still-secret\n", encoding="utf-8")
        (self.repo / "logs" / "should_not_stage.log").write_text("nope\n", encoding="utf-8")
        self._set_state(validate_exit=0, consistency_exit=0, generate_selected=0)
        proc = self._run("push_script.sh")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        show = subprocess.run(
            ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )
        names = [n for n in show.stdout.splitlines() if n.strip()]
        self.assertTrue(any(n.startswith("TLDR/") for n in names))
        self.assertFalse(any(n.startswith("logs/") for n in names))
        self.assertFalse(any(n == ".env" or n.endswith("/.env") for n in names))

    def test_modeled_openrouter_fallback_does_not_block_ingestion(self) -> None:
        (self.repo / "TLDR" / "article_02-02-2024.md").write_text("# fallback source\n", encoding="utf-8")
        self._set_state(editorial_status="deterministic_fallback")
        proc = self._run("push_script.sh")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        self.assertEqual(self._rev(), self._remote_rev())
        self.assertTrue((self.repo / "logs" / "last_push_success").is_file())

    def test_modeled_r2_editorial_only_does_not_block_ingestion(self) -> None:
        (self.repo / "TLDR" / "article_03-02-2024.md").write_text("# r2 fallback source\n", encoding="utf-8")
        self._set_state(editorial_status="editorial_only")
        proc = self._run("push_script.sh")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        self.assertEqual(self._rev(), self._remote_rev())

    def test_editorial_cli_nonzero_blocks_commit_and_success_marker(self) -> None:
        (self.repo / "TLDR" / "article_04-02-2024.md").write_text("# internal failure\n", encoding="utf-8")
        before = self._rev()
        self._set_state(editorial_generate_fail_on_call=1)
        proc = self._run("push_script.sh")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(before, self._rev())
        self.assertFalse((self.repo / "logs" / "last_push_success").exists())

    def test_validation_failure_prevents_commit(self) -> None:
        (self.repo / "TLDR" / "article_03-01-2024.md").write_text(
            "# Articles TLDR 03-01-2024\n\nNEW\n", encoding="utf-8"
        )
        before = self._rev()
        self._set_state(validate_exit=2)
        proc = self._run("push_script.sh")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(before, self._rev())

    def test_structural_failure_prevents_commit(self) -> None:
        (self.repo / "TLDR" / "article_04-01-2024.md").write_text(
            "# Articles TLDR 04-01-2024\n\nNEW\n", encoding="utf-8"
        )
        before = self._rev()
        self._set_state(validate_exit=0, consistency_exit=3)
        proc = self._run("push_script.sh")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(before, self._rev())

    def test_selected_nonzero_prevents_commit(self) -> None:
        (self.repo / "TLDR" / "article_05-01-2024.md").write_text(
            "# Articles TLDR 05-01-2024\n\nNEW\n", encoding="utf-8"
        )
        before = self._rev()
        self._set_state(
            validate_exit=0,
            consistency_exit=0,
            generate_selected=1,
            generate_written=1,
        )
        proc = self._run("push_script.sh")
        self.assertNotEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        self.assertEqual(before, self._rev())

    def test_successful_push_commits_and_pushes(self) -> None:
        (self.repo / "TLDR" / "article_06-01-2024.md").write_text(
            "# Articles TLDR 06-01-2024\n\nNEW\n", encoding="utf-8"
        )
        self._set_state(
            validate_exit=0,
            consistency_exit=0,
            generate_selected=0,
            generate_written=0,
        )
        before = self._rev()
        proc = self._run("push_script.sh")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        after = self._rev()
        self.assertNotEqual(before, after)
        self.assertTrue((self.repo / "logs" / "last_push_success").is_file())
        self.assertEqual(after, self._remote_rev())
        log = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertTrue(log.startswith("Daily TLDR update "))

    def test_failed_push_retried_on_next_invocation(self) -> None:
        # Create a local commit that is ahead of origin, simulating a failed push.
        (self.repo / "TLDR" / "article_07-01-2024.md").write_text(
            "# Articles TLDR 07-01-2024\n\nLOCAL ONLY\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "TLDR/article_07-01-2024.md"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "local unpushed daily"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        local = self._rev()
        self.assertNotEqual(local, self._remote_rev())

        self._set_state(validate_exit=0, consistency_exit=0, generate_selected=0)
        proc = self._run("push_script.sh")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        self.assertEqual(self._rev(), self._remote_rev())
        self.assertIn("pushed", proc.stdout)

    def test_no_staged_changes_still_pulls_origin(self) -> None:
        # Advance origin with a commit the local checkout does not have yet.
        remote_tip = self._plant_remote_only_commit(
            "TLDR/article_08-01-2024.md",
            "# Articles TLDR 08-01-2024\n\nFROM REMOTE\n",
            "remote advance",
        )

        self._set_state(validate_exit=0, consistency_exit=0, generate_selected=0)
        proc = self._run("push_script.sh")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        self.assertEqual(self._rev(), remote_tip)
        self.assertTrue(
            (self.repo / "TLDR" / "article_08-01-2024.md").is_file()
        )
        self.assertIn("pull --rebase completed", proc.stdout)
        self.assertTrue((self.repo / "logs" / "last_push_success").is_file())

    def test_remote_commit_triggers_post_rebase_checks(self) -> None:
        self._plant_remote_only_commit(
            "TLDR/article_09-01-2024.md",
            "# Articles TLDR 09-01-2024\n\nREMOTE\n",
            "remote md",
        )

        self._set_state(validate_exit=0, consistency_exit=0, generate_selected=0)
        before_validate = self._state()["validate_calls"]
        proc = self._run("push_script.sh")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        self.assertIn("post-rebase validate passed", proc.stdout)
        self.assertGreater(self._state()["validate_calls"], before_validate)
        self.assertGreaterEqual(self._state()["generate_calls"], 2)
        self.assertGreaterEqual(self._state()["editorial_generate_calls"], 2)

    def test_editorial_cli_nonzero_post_rebase_blocks_push(self) -> None:
        (self.repo / "TLDR" / "article_09b-01-2024.md").write_text("# local ahead\n", encoding="utf-8")
        subprocess.run(["git", "add", "TLDR/article_09b-01-2024.md"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "local pending"], cwd=self.repo, check=True, capture_output=True)
        local = self._rev(); remote = self._remote_rev(); self.assertNotEqual(local, remote)
        self._set_state(editorial_generate_fail_on_call=2)
        proc = self._run("push_script.sh")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self._remote_rev(), remote)
        self.assertFalse((self.repo / "logs" / "last_push_success").exists())

    def test_post_rebase_validation_failure_prevents_push(self) -> None:
        # Local unpushed commit + remote tip equal initially; make validate fail
        # only after the first pre-commit path is skipped (noop staging), i.e. on
        # post-rebase validate. With clean tree, validate runs only post-rebase.
        (self.repo / "TLDR" / "article_10-01-2024.md").write_text(
            "# Articles TLDR 10-01-2024\n\nLOCAL\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "TLDR/article_10-01-2024.md"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "local ahead"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        local = self._rev()
        self.assertNotEqual(local, self._remote_rev())

        # No staged changes on next run; post-rebase validate fails.
        self._set_state(validate_exit=9, consistency_exit=0, generate_selected=0)
        proc = self._run("push_script.sh")
        self.assertNotEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        self.assertNotEqual(self._remote_rev(), local)
        self.assertFalse((self.repo / "logs" / "last_push_success").exists())

    def test_wrong_branch_fails_before_git_work(self) -> None:
        subprocess.run(
            ["git", "checkout", "-b", "feature/not-main"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        before = self._rev()
        remote_before = self._remote_rev()
        proc = self._run("push_script.sh")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("expected branch main", proc.stdout)
        self.assertEqual(before, self._rev())
        self.assertEqual(remote_before, self._remote_rev())
        self.assertEqual(self._state()["generate_calls"], 0)

    def test_missing_flock_fails_clearly(self) -> None:
        env = self._env()
        # Remove shim directory from PATH.
        env["PATH"] = "/usr/bin:/bin"
        proc = subprocess.run(
            ["bash", str(self.repo / "push_script.sh")],
            cwd=self.repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        # On Ubuntu CI, real flock exists — skip assertion if so.
        if shutil.which("flock", path="/usr/bin:/bin"):
            self.skipTest("system flock present")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("flock is required", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
