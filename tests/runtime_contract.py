"""Checks every runtime adapter must pass, against its recorded fixtures (tests/fixtures/runtimes/<name>/)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
sys.path.insert(0, str(PLUGIN / "vendor" / "factory" / "factory" / "lib"))
FIXTURES = REPO / "tests" / "fixtures" / "runtimes"


class RuntimeContract:
    """Mixin: set NAME; the adapter is runtimes.load(NAME)."""
    NAME = None
    RESULT = "result.out"

    def setUp(self):
        import runtimes
        self.rt = runtimes.load(self.NAME)
        self.fixtures = FIXTURES / self.NAME
        if not (self.fixtures / self.RESULT).exists():
            self.skipTest(f"no recorded {self.NAME} output; see Task 1 of the 6b plan")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        (self.repo / "factory").mkdir()
        (self.repo / "factory" / "runner-settings.json").write_text("{}")
        self.runs = self.repo / "factory" / "jobs" / "004-x" / "runs"
        self.runs.mkdir(parents=True)
        (self.runs / "s.system.md").write_text("SYSTEM PROMPT\n")
        (self.runs / "s.prompt.md").write_text("TASK PROMPT\n")

    def run_for(self, role="builder", access="write", resume=None):
        return {"repo": self.repo, "job_id": "004-x", "role": role, "access": access, "model": "m1",
                "effort": "high", "system_path": self.runs / "s.system.md", "prompt_path": self.runs / "s.prompt.md",
                "settings_dir": self.runs, "stem": "s", "resume": resume,
                "session_id": "11111111-1111-4111-8111-111111111111"}

    def test_caps_shape(self):
        self.assertEqual(set(self.rt.CAPS), {"resume", "reports_cost", "reports_tokens", "efforts", "stop_hook", "silent_new_session"})
        self.assertEqual(self.rt.NAME, self.NAME)
        self.assertTrue(self.rt.BINARY)

    def test_build_starts_the_binary_with_model_and_job_env(self):
        argv, env = self.rt.build(self.run_for())
        self.assertEqual(Path(argv[0]).name, self.rt.BINARY)
        self.assertIn("m1", argv)
        self.assertEqual(env.get("FACTORY_JOB"), "004-x")
        self.assertEqual(env.get("FACTORY_RUNNER"), "1")

    def test_system_prompt_reaches_the_agent(self):
        argv, _ = self.rt.build(self.run_for())
        files = "".join(Path(a).read_text() for a in argv if a.startswith("/") and Path(a).is_file())
        delivered = " ".join(argv) + (self.runs / "s.prompt.md").read_text() + files   # claude passes a file
        self.assertIn("SYSTEM PROMPT", delivered)
        self.assertIn("TASK PROMPT", delivered)

    def test_resume_is_passed_when_supported(self):
        argv, _ = self.rt.build(self.run_for(resume="sess-42"))
        self.assertEqual("sess-42" in argv, self.rt.CAPS["resume"])

    def test_recorded_result(self):
        r = self.rt.parse((self.fixtures / self.RESULT).read_text())
        self.assertFalse(r["error"])
        if self.rt.CAPS["resume"]:
            self.assertTrue(r["session_id"])
        if self.rt.CAPS["reports_cost"]:
            self.assertIsNotNone(r["cost_usd"])
        if self.rt.CAPS["reports_tokens"]:
            self.assertGreater(r["usage"]["input_tokens"] + r["usage"]["output_tokens"], 0)
        self.assertEqual(set(r), {"session_id", "model", "usage", "cost_usd", "cost_source", "cost_by_model", "error",
                                  "limit"})
        self.assertIsNone(r["limit"])

    def test_recorded_resume_keeps_the_session(self):
        if not self.rt.CAPS["resume"]:
            self.skipTest("runtime can't resume")
        first = self.rt.parse((self.fixtures / self.RESULT).read_text())
        again = self.rt.parse((self.fixtures / "resumed.out").read_text())
        self.assertEqual(again["session_id"], first["session_id"])

    def test_recorded_error_is_an_error_or_unreadable(self):
        try:
            self.assertTrue(self.rt.parse((self.fixtures / "error.out").read_text())["error"])
        except ValueError:
            pass

    def test_empty_output_is_unreadable(self):
        with self.assertRaises(ValueError):
            self.rt.parse("")
