import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
LIB = PLUGIN / "vendor" / "factory" / "factory" / "lib"
FIXTURES = PLUGIN / "tests" / "fixtures" / "runtimes" / "claude"
sys.path.insert(0, str(LIB))

import runtimes  # noqa: E402
from runtimes import claude  # noqa: E402


class LoadTest(unittest.TestCase):
    def test_load_claude(self):
        self.assertIs(runtimes.load("claude"), claude)

    def test_unknown_runtime_names_the_known_ones(self):
        with self.assertRaisesRegex(ValueError, "unknown runtime 'nope'; known: claude"):
            runtimes.load("nope")


class BuildTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        (self.repo / "factory").mkdir()
        (self.repo / "factory" / "runner-settings.json").write_text(json.dumps(
            {"permissions": {"deny": ["Read(./.env)"]}, "sandbox": {"enabled": True}}))
        self.runs = self.repo / "runs"
        self.runs.mkdir()

    def run_for(self, role, **extra):
        return {"repo": self.repo, "job_id": "004-x", "role": role, "access": "read", "model": "opus",
                "effort": "high", "system_path": self.runs / "s.system.md", "settings_dir": self.runs,
                "stem": "s", "resume": None, "session_id": "11111111-1111-4111-8111-111111111111", **extra}

    def test_reviewer_argv_env_and_settings(self):
        argv, env = claude.build(self.run_for("reviewer-code"))
        self.assertEqual(argv[:2], ["claude", "-p"])
        for flag, value in (("--output-format", "json"), ("--model", "opus"), ("--effort", "high"),
                            ("--append-system-prompt-file", str(self.runs / "s.system.md")),
                            ("--tools", "Read,Grep,Glob,Bash,Write"),
                            ("--settings", str(self.runs / "s.settings.json")),
                            ("--permission-mode", "dontAsk"),
                            ("--session-id", "11111111-1111-4111-8111-111111111111")):
            self.assertEqual(argv[argv.index(flag) + 1], value, flag)
        self.assertNotIn("--resume", argv)
        self.assertEqual(env, {"CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1", "FACTORY_RUNNER": "1",
                               "FACTORY_JOB": "004-x"})
        written = json.loads((self.runs / "s.settings.json").read_text())
        self.assertEqual(written, {"permissions": {"deny": ["Read(./.env)"]}, "sandbox": {"enabled": True}})

    def test_builder_gets_its_tools_and_the_gate_stop_hook(self):
        argv, _ = claude.build(self.run_for("builder", access="write"))
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob,Bash,Edit,Write,Skill")
        hooks = json.loads((self.runs / "s.settings.json").read_text())["hooks"]["Stop"]
        self.assertEqual(hooks, [{"hooks": [{"type": "command",
                                             "command": f'"{self.repo}/factory/bin/gate" --hook'}]}])

    def test_resume_replaces_session_id(self):
        argv, _ = claude.build(self.run_for("builder", access="write", resume="abc"))
        self.assertEqual(argv[argv.index("--resume") + 1], "abc")
        self.assertNotIn("--session-id", argv)

    def test_every_role_has_tools(self):
        for role in ("intake", "spec-writer", "builder", "approver", "learner",
                     "reviewer-code", "reviewer-security", "reviewer-ux", "reviewer-ui"):
            self.assertTrue(claude.tools(role), role)
        self.assertEqual(claude.tools("intake"), "Read,Grep,Glob,Write")


class ParseTest(unittest.TestCase):
    def test_recorded_result(self):
        r = claude.parse((FIXTURES / "result.json").read_text())
        self.assertFalse(r["error"])
        self.assertRegex(r["session_id"], r"^[0-9a-f-]{36}$")
        self.assertGreater(r["cost_usd"], 0)
        self.assertEqual(r["cost_source"], "cli")
        self.assertIn(r["model"], r["cost_by_model"])
        self.assertAlmostEqual(sum(r["cost_by_model"].values()), r["cost_usd"], places=4)
        self.assertIn("input_tokens", r["usage"])

    def test_recorded_resume_keeps_the_session(self):
        first = claude.parse((FIXTURES / "result.json").read_text())
        again = claude.parse((FIXTURES / "resumed.json").read_text())
        self.assertEqual(again["session_id"], first["session_id"])

    def test_recorded_error_is_an_error_or_unreadable(self):
        text = (FIXTURES / "error.json").read_text()
        try:
            self.assertTrue(claude.parse(text)["error"])
        except ValueError:
            pass

    def test_no_result_object_is_a_value_error(self):
        for text in ("", "not json", json.dumps({"type": "system"})):
            with self.assertRaises(ValueError):
                claude.parse(text)

    def test_missing_cost_is_none(self):
        r = claude.parse(json.dumps({"type": "result", "session_id": "s", "is_error": False}))
        self.assertEqual((r["cost_usd"], r["cost_source"], r["model"], r["cost_by_model"]), (None, None, None, {}))


if __name__ == "__main__":
    unittest.main()
