import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from installed_project import VENDOR, load_script

SECRETS = {"CLAUDE_CODE_OAUTH_TOKEN": "tok", "ANTHROPIC_API_KEY": "key",
           "ANTHROPIC_AUTH_TOKEN": "auth", "ANTHROPIC_BASE_URL": "http://x"}


class GateEnvTest(unittest.TestCase):
    def test_checks_run_without_claude_credentials(self):
        gate = load_script("gate_under_test", VENDOR / "factory/bin/gate")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "env.txt"
            script = Path(tmp) / "checks.sh"
            script.write_text(f"env > '{out}'\n")
            with mock.patch.object(gate, "CHECKS", script), mock.patch.dict(os.environ, SECRETS):
                code, _, _ = gate.run_checks(tmp)
            seen = out.read_text()
        self.assertEqual(code, 0)
        self.assertIn("PATH=", seen)
        for name in SECRETS:
            self.assertNotIn(name, seen)


class GateHookCase(unittest.TestCase):
    """gate --hook against a job whose worktree fails checks.sh."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.job_id = "004-x"
        folder = root / "factory" / "jobs" / self.job_id
        folder.mkdir(parents=True)
        (root / "wt").mkdir()
        (folder / "job.json").write_text(json.dumps({"id": self.job_id, "worktree": str(root / "wt")}))
        checks = root / "checks.sh"
        checks.write_text("echo broken\nexit 1\n")
        self.gate = load_script("gate_hook_under_test", VENDOR / "factory/bin/gate")
        for name, value in (("FACTORY", root / "factory"), ("CHECKS", checks)):
            patcher = mock.patch.object(self.gate, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_hook(self, event, env=None):
        err = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(event))), mock.patch.dict(os.environ, env or {}), \
                contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            self.gate.hook()
        return ctx.exception.code, err.getvalue()


class HookJobFromEnvTest(GateHookCase):
    def test_factory_job_env_wins_over_the_transcript(self):
        event = {"stop_hook_active": False, "transcript_path": "/nonexistent"}
        code, err = self.run_hook(event, env={"FACTORY_JOB": self.job_id})
        self.assertEqual(code, 2)
        self.assertIn("checks.sh fails in your worktree", err)


if __name__ == "__main__":
    unittest.main()
