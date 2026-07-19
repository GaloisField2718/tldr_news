"""Offline tests for validated web redeployment workflow behavior."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "derive-ci.yml"
SECRET_CANARY = "https://example.invalid/a-secret-hook-value"


def extract_marked_block(text: str, start: str, end: str) -> str:
    """Extract and de-indent one marker-delimited workflow shell block."""
    lines = text.splitlines()
    start_index = next(i for i, line in enumerate(lines) if start in line)
    end_index = next(i for i, line in enumerate(lines) if i > start_index and end in line)
    return textwrap.dedent("\n".join(lines[start_index + 1 : end_index]))


def extract_deploy_condition(text: str) -> str:
    """Return the actual deploy-web job expression as one evaluable line."""
    match = re.search(
        r"(?m)^  deploy-web:\n[\s\S]*?^    if: >-\n(?P<condition>(?:^      [^\n]*\n)+)",
        text,
    )
    if not match:
        raise AssertionError("deploy-web condition was not found")
    return " ".join(line.strip() for line in match.group("condition").splitlines())


class WorkflowStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.deploy_condition = extract_deploy_condition(cls.workflow)

    def deploys_for(self, event_name: str, ref: str, deploy_web: bool) -> bool:
        expression = self.deploy_condition.replace("&&", " and ").replace("||", " or ")
        expression = re.sub(r"\btrue\b", "True", expression)
        return bool(
            eval(
                expression,
                {"__builtins__": {}},
                {
                    "github": SimpleNamespace(event_name=event_name, ref=ref),
                    "inputs": SimpleNamespace(deploy_web=deploy_web),
                },
            )
        )

    def test_validation_triggers_and_read_only_permissions(self) -> None:
        self.assertIn("pull_request:", self.workflow)
        self.assertRegex(self.workflow, r"push:\s+branches:\s+- main")
        self.assertNotIn("feat/tldr-derived-data-foundation", self.workflow)
        self.assertNotIn("feat/daily-ingestion-derived-sync", self.workflow)
        self.assertRegex(self.workflow, r"permissions:\s+contents: read")
        for forbidden in (
            "contents: write",
            "actions: write",
            "deployments: write",
            "pull-requests: write",
        ):
            self.assertNotIn(forbidden, self.workflow)

    def test_manual_dispatch_defaults_to_validation_only(self) -> None:
        self.assertRegex(
            self.workflow,
            r"(?s)workflow_dispatch:\s+inputs:\s+deploy_web:.*?default: false.*?type: boolean",
        )

    def test_deploy_job_depends_on_successful_validation(self) -> None:
        deploy = self.workflow.split("  deploy-web:", 1)[1]
        self.assertIn("needs: validate-derived-data", deploy)
        self.assertNotIn("actions/checkout", deploy)
        self.assertNotIn("always()", deploy)

    def test_manual_deployment_condition_structurally_requires_main(self) -> None:
        self.assertRegex(
            self.deploy_condition,
            r"\(github\.event_name == 'workflow_dispatch'\s+&&\s+"
            r"github\.ref == 'refs/heads/main'\s+&&\s+inputs\.deploy_web == true\)",
        )

    def test_push_to_main_may_deploy(self) -> None:
        self.assertTrue(self.deploys_for("push", "refs/heads/main", False))
        self.assertFalse(self.deploys_for("push", "refs/heads/feature", True))

    def test_manual_deployment_on_main_may_deploy(self) -> None:
        self.assertTrue(self.deploys_for("workflow_dispatch", "refs/heads/main", True))

    def test_manual_deployment_on_non_main_ref_cannot_deploy(self) -> None:
        self.assertFalse(
            self.deploys_for("workflow_dispatch", "refs/heads/feature/test", True)
        )

    def test_manual_dispatch_with_deploy_disabled_cannot_deploy(self) -> None:
        self.assertFalse(self.deploys_for("workflow_dispatch", "refs/heads/main", False))

    def test_pull_requests_cannot_deploy(self) -> None:
        self.assertFalse(self.deploys_for("pull_request", "refs/pull/8/merge", True))

    def test_concurrency_cancels_older_runs_for_the_same_ref(self) -> None:
        self.assertIn("group: ${{ github.workflow }}-${{ github.ref }}", self.workflow)
        self.assertIn("cancel-in-progress: true", self.workflow)

    def test_validation_commands_remain_strict(self) -> None:
        for command in (
            "bash -n automation.sh",
            "bash -n push_script.sh",
            "python3 -m unittest tests_derive.test_derive",
            "python3 -m unittest tests_pipeline.test_daily_pipeline",
            "python3 -m tools.tldr_derive validate --all --strict-privacy",
            "python3 -m tools.check_generated_consistency --output generated",
        ):
            self.assertIn(command, self.workflow)
        self.assertNotIn("continue-on-error", self.workflow)

    def test_hook_request_is_bounded_and_uses_no_auth_header_or_payload(self) -> None:
        deploy = self.workflow.split("  deploy-web:", 1)[1]
        for option in (
            "--request POST",
            "--fail-with-body",
            "--silent",
            "--show-error",
            "--connect-timeout 10",
            "--max-time 60",
            "--retry 3",
            "--retry-connrefused",
        ):
            self.assertIn(option, deploy)
        self.assertNotIn("Authorization", deploy)
        self.assertNotIn("--data", deploy)


class DeployShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.deploy_script = extract_marked_block(
            workflow, "# DEPLOY_SCRIPT_BEGIN", "# DEPLOY_SCRIPT_END"
        )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        fake_curl = Path(self.temporary.name) / "curl"
        fake_curl.write_text(
            "#!/usr/bin/env bash\nprintf '%s' \"${FAKE_CURL_RESPONSE:-}\"\n",
            encoding="utf-8",
        )
        fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IXUSR)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_deploy(self, response: object | str, *, include_secret: bool = True) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PATH"] = f"{self.temporary.name}:{env['PATH']}"
        env["FAKE_CURL_RESPONSE"] = response if isinstance(response, str) else json.dumps(response)
        if include_secret:
            env["VERCEL_DEPLOY_HOOK_URL"] = SECRET_CANARY
        else:
            env.pop("VERCEL_DEPLOY_HOOK_URL", None)
        return subprocess.run(
            ["bash", "-c", self.deploy_script],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def assert_secret_not_logged(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotIn(SECRET_CANARY, result.stdout)
        self.assertNotIn(SECRET_CANARY, result.stderr)

    def test_missing_secret_fails_before_request_without_logging_a_url(self) -> None:
        result = self.run_deploy({"job": {"id": "unused"}}, include_secret=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VERCEL_DEPLOY_HOOK_URL is not configured", result.stderr + result.stdout)
        self.assert_secret_not_logged(result)

    def test_malformed_json_fails_safely(self) -> None:
        result = self.run_deploy("not-json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid deployment response", result.stderr)
        self.assert_secret_not_logged(result)

    def test_response_without_job_id_fails_safely(self) -> None:
        result = self.run_deploy({"job": {"state": "PENDING"}})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid deployment response", result.stderr)
        self.assert_secret_not_logged(result)

    def test_explicit_error_response_fails_safely(self) -> None:
        result = self.run_deploy({"error": {"message": "rejected"}})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid deployment response", result.stderr)
        self.assertNotIn("rejected", result.stderr + result.stdout)
        self.assert_secret_not_logged(result)

    def test_valid_response_prints_only_safe_job_metadata(self) -> None:
        result = self.run_deploy({"job": {"id": "job_123", "state": "QUEUED"}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "Vercel deployment requested successfully",
                "job_id=job_123",
                "state=QUEUED",
            ],
        )
        self.assert_secret_not_logged(result)


if __name__ == "__main__":
    unittest.main()
