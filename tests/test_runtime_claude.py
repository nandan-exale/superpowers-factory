import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
LIB = PLUGIN / "vendor" / "factory" / "factory" / "lib"
FIXTURES = PLUGIN / "tests" / "fixtures" / "runtimes" / "claude"
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import runtimes  # noqa: E402
from runtime_contract import RuntimeContract  # noqa: E402
from runtimes import claude  # noqa: E402


class LoadTest(unittest.TestCase):
    def test_load_claude(self):
        self.assertIs(runtimes.load("claude"), claude)

    def test_unknown_runtime_names_the_known_ones(self):
        with self.assertRaisesRegex(ValueError, "unknown runtime 'nope'; known: claude"):
            runtimes.load("nope")

    def test_every_runtime_is_known(self):
        self.assertEqual(runtimes.NAMES, ("claude", "codex", "opencode", "copilot", "cursor"))

    def test_claude_names_its_npm_package(self):
        self.assertEqual(claude.NPM_PACKAGE, "@anthropic-ai/claude-code")


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

    def test_user_settings_are_not_loaded(self):
        # A user-level `ask` rule such as Bash(git commit:*) beats runner-settings' allow, and with
        # no one to answer it the builder's commit is denied.
        argv, _ = claude.build(self.run_for("builder", access="write"))
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project,local")

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


LIMIT_TEXT = "You've hit your 5-hour limit · resets 6:50pm (Europe/Stockholm)"


class LimitTest(unittest.TestCase):
    """A usage limit isn't a failure: the orchestrator waits for the reset instead of escalating.

    claude -p's result for a limit hasn't been recorded; the text is what the interactive session
    showed on 2026-11-13 (error rate_limit / usage_limit_reached)."""

    def result(self, text, is_error=True, **extra):
        return json.dumps({"type": "result", "session_id": "s", "is_error": is_error, "result": text, **extra})

    def test_a_limit_result_is_a_limit_with_its_reset_time(self):
        r = claude.parse(self.result(LIMIT_TEXT))
        self.assertTrue(r["error"])
        self.assertEqual(r["limit"]["message"], LIMIT_TEXT)
        self.assertEqual(r["limit"]["until"].tzinfo, timezone.utc)

    def test_a_429_is_a_limit_whatever_the_text(self):
        self.assertIsNotNone(claude.parse(self.result("Request rejected", api_error_status=429))["limit"])

    def test_other_errors_and_successes_are_not_limits(self):
        self.assertIsNone(claude.parse(self.result("No conversation found"))["limit"])
        self.assertIsNone(claude.parse(self.result("I checked the rate limit code.", is_error=False))["limit"])

    def test_reset_time_is_the_next_one_in_that_zone(self):
        before = datetime(2026, 11, 13, 14, 23, tzinfo=timezone.utc)  # 15:23 in Stockholm
        self.assertEqual(claude.reset_time(LIMIT_TEXT, before), datetime(2026, 11, 13, 17, 50, tzinfo=timezone.utc))
        after = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)  # 19:00 in Stockholm: tomorrow's 6:50pm
        self.assertEqual(claude.reset_time(LIMIT_TEXT, after), datetime(2026, 11, 14, 17, 50, tzinfo=timezone.utc))

    def test_reset_time_reads_am_and_a_bare_hour(self):
        now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(claude.reset_time("resets 9am (UTC)", now), datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc))
        self.assertEqual(claude.reset_time("resets 12pm (UTC)", now), datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc))

    def test_unreadable_reset_time_is_none(self):
        now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        for text in ("You've hit your limit", "resets 6:50pm (Not/AZone)", "resets 13pm (UTC)"):
            with self.subTest(text=text):
                self.assertIsNone(claude.reset_time(text, now))


class ClaudeContractTest(RuntimeContract, unittest.TestCase):
    NAME = "claude"
    RESULT = "result.json"

    def test_recorded_resume_keeps_the_session(self):
        first = self.rt.parse((self.fixtures / self.RESULT).read_text())
        again = self.rt.parse((self.fixtures / "resumed.json").read_text())
        self.assertEqual(again["session_id"], first["session_id"])

    def test_recorded_error_is_an_error_or_unreadable(self):
        try:
            self.assertTrue(self.rt.parse((self.fixtures / "error.json").read_text())["error"])
        except ValueError:
            pass


if __name__ == "__main__":
    unittest.main()
