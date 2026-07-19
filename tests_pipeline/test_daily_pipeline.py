"""Offline tests for daily automation.sh / push_script.sh orchestration.

Does not execute the real script.py, read .env, or contact IMAP/network remotes
outside a temporary local git bare repository.
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


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class ScriptStaticGuards(unittest.TestCase):
    def test_bash_syntax(self) -> None:
        for script in (AUTOMATION, PUSH):
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
            self.assertNotIn("source activate", text)
            self.assertNotIn(". activate", text)
            self.assertTrue(text.startswith("#!/usr/bin/env bash"))
            self.assertIn("set -Eeuo pipefail", text)
            self.assertIn("acquire_pipeline_lock", text)
        lib = (REPO / "scripts" / "pipeline_lib.sh").read_text(encoding="utf-8")
        self.assertIn("flock -n", lib)
        self.assertIn("fcntl.flock", lib)

    def test_push_stages_only_approved_paths(self) -> None:
        text = PUSH.read_text(encoding="utf-8")
        self.assertIn("git add -A -- \"${directory}\"", text)
        self.assertIn("generated/manifest.json", text)
        self.assertIn("generated/issues", text)
        self.assertNotIn("git add .", text)


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
        self.repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo, check=True, capture_output=True)
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
        # Minimal tracked tree.
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
        issue_path = self.repo / "generated" / "issues" / "tldr" / "2024" / "2024-01-01.json"
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
        # Copy orchestration scripts and a stub tools package path via PYTHONPATH=REPO
        shutil.copy2(AUTOMATION, self.repo / "automation.sh")
        shutil.copy2(PUSH, self.repo / "push_script.sh")
        (self.repo / "scripts").mkdir(exist_ok=True)
        shutil.copy2(REPO / "scripts" / "pipeline_lib.sh", self.repo / "scripts" / "pipeline_lib.sh")
        (self.repo / "automation.sh").chmod(0o755)
        (self.repo / "push_script.sh").chmod(0o755)
        (self.repo / "script.py").write_text("# placeholder; never executed by real IMAP\n", encoding="utf-8")
        # tools package comes from REPO via PYTHONPATH
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "init", "--bare", str(self.bare)], check=True, capture_output=True)
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
                    "generate_selected": 0,
                    "generate_written": 0,
                    "validate_exit": 0,
                    "consistency_exit": 0,
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
        content = textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            STATE="{state_path}"
            py_update() {{
              /usr/bin/env python3 - "$STATE" "$@" <<'PY'
            import json, sys
            path = sys.argv[1]
            key = sys.argv[2]
            delta = int(sys.argv[3]) if len(sys.argv) > 3 else 1
            doc = json.loads(open(path, encoding="utf-8").read())
            if key.endswith("_exit") or key.endswith("_selected") or key.endswith("_written"):
                doc[key] = delta
            else:
                doc[key] = doc.get(key, 0) + delta
            open(path, "w", encoding="utf-8").write(json.dumps(doc))
            print(json.dumps(doc.get(key)))
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

            # Inline python -c used by push_script for changed_clean parsing.
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
        env.update(
            {
                "REPO_ROOT": str(self.repo),
                "PYTHON_BIN": str(self.python_bin),
                "LOCK_FILE": str(self.lock),
                "LOG_DIR": str(self.repo / "logs"),
                "REMOTE": "origin",
                "BRANCH": "main",
                # Ensure -m tools.* resolves if mock shells out incorrectly.
                "PYTHONPATH": str(REPO),
            }
        )
        return env

    def _run(self, script: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.repo / script)],
            cwd=self.repo,
            env=self._env(),
            check=check,
            capture_output=True,
            text=True,
        )

    def test_lock_contention_exits_cleanly(self) -> None:
        # Hold the lock with a long-lived process sharing the open file description.
        holder = subprocess.Popen(
            [
                "python3",
                "-c",
                f"""
import fcntl, os, time
fd = os.open({str(self.lock)!r}, os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
time.sleep(8)
""",
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
        self.assertEqual(st["generate_calls"], 1)
        self.assertTrue((self.repo / "logs" / "last_automation_success").is_file())

    def test_push_exits_zero_when_nothing_to_commit(self) -> None:
        # Working tree clean vs HEAD.
        proc = self._run("push_script.sh")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        self.assertIn("nothing to commit", proc.stdout)
        self.assertEqual(self._state()["validate_calls"], 0)

    def test_push_does_not_stage_logs_or_env(self) -> None:
        (self.repo / "TLDR" / "article_02-01-2024.md").write_text(
            "# Articles TLDR 02-01-2024\n\nNEW\n", encoding="utf-8"
        )
        (self.repo / ".env").write_text("SECRET=still-secret\n", encoding="utf-8")
        (self.repo / "logs" / "should_not_stage.log").write_text("nope\n", encoding="utf-8")
        # Make validate/consistency/generate succeed.
        self._set_state(validate_exit=0, consistency_exit=0, generate_selected=0)
        proc = self._run("push_script.sh")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        # Inspect latest commit paths.
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

    def test_validation_failure_prevents_commit(self) -> None:
        (self.repo / "TLDR" / "article_03-01-2024.md").write_text(
            "# Articles TLDR 03-01-2024\n\nNEW\n", encoding="utf-8"
        )
        before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self._set_state(validate_exit=2)
        proc = self._run("push_script.sh")
        self.assertNotEqual(proc.returncode, 0)
        after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(before, after)
        self.assertEqual(self._state()["consistency_calls"], 0)

    def test_structural_failure_prevents_commit(self) -> None:
        (self.repo / "TLDR" / "article_04-01-2024.md").write_text(
            "# Articles TLDR 04-01-2024\n\nNEW\n", encoding="utf-8"
        )
        before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self._set_state(validate_exit=0, consistency_exit=3)
        proc = self._run("push_script.sh")
        self.assertNotEqual(proc.returncode, 0)
        after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(before, after)

    def test_selected_nonzero_prevents_commit(self) -> None:
        (self.repo / "TLDR" / "article_05-01-2024.md").write_text(
            "# Articles TLDR 05-01-2024\n\nNEW\n", encoding="utf-8"
        )
        before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        # Initial generate can be anything; final generate must be unclean.
        # push_script calls generate twice; make every generate report selected=1.
        self._set_state(
            validate_exit=0,
            consistency_exit=0,
            generate_selected=1,
            generate_written=1,
        )
        proc = self._run("push_script.sh")
        self.assertNotEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(before, after)

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
        before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        proc = self._run("push_script.sh")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertNotEqual(before, after)
        self.assertTrue((self.repo / "logs" / "last_push_success").is_file())
        remote_head = subprocess.run(
            ["git", "--git-dir", str(self.bare), "rev-parse", "main"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(after, remote_head)
        log = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertTrue(log.startswith("Daily TLDR update "))
        self.assertIn("UTC", log)


if __name__ == "__main__":
    unittest.main()
