"""scripts/check skips the unit tests for a docs-only change reported by the Stop hook."""

import contextlib
import io
import os
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from script_loader import load_script

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check"
CHECK = load_script(SCRIPT, "check_docs_skip_script")


def hook_env(paths, context="stop-hook"):
    env = {} if context is None else {"FACTORY_CHECKS_CONTEXT": context}
    if paths is not None:
        env["FACTORY_CHANGED_PATHS"] = "\n".join(paths)
    return env


class SkipDecisionTest(unittest.TestCase):
    def test_docs_and_markdown_skip(self):
        paths = ["docs/superpowers/specs/x.md", "README.md", "docs/notes.txt"]
        self.assertTrue(CHECK.skip_tests_for_docs(hook_env(paths)))

    def test_paths_that_need_the_tests_run_them(self):
        for paths in (
            ["scripts/check.py"],
            ["README.md", "scripts/x.py"],
            ["plugin/vendor/factory/factory/agents/builder.md"],
            ["plugin/skills/factory-install/SKILL.md"],
            [".claude/skills/factory/SKILL.md"],
            ["plugin/vendor/factory/.claude/skills/factory/SKILL.md"],
            ["plugin/vendor/factory/INSTALL.md"],
            ["../x.md"],
            ["docs/../scripts/x.md"],
            ["/abs/x.md"],
            ["README.MD"],
            [],
        ):
            with self.subTest(paths=paths):
                self.assertFalse(CHECK.skip_tests_for_docs(hook_env(paths)))

    def test_blank_lines_are_ignored_but_a_list_of_only_blanks_runs_the_tests(self):
        self.assertTrue(CHECK.skip_tests_for_docs({"FACTORY_CHECKS_CONTEXT": "stop-hook",
                                                   "FACTORY_CHANGED_PATHS": "\nREADME.md\n\n"}))
        self.assertFalse(CHECK.skip_tests_for_docs({"FACTORY_CHECKS_CONTEXT": "stop-hook",
                                                    "FACTORY_CHANGED_PATHS": "\n \n"}))

    def test_without_the_stop_hook_context_the_tests_run(self):
        for context in (None, "ci", "stop-hook "):
            with self.subTest(context=context):
                self.assertFalse(CHECK.skip_tests_for_docs(hook_env(["README.md"], context)))

    def test_a_missing_list_runs_the_tests(self):
        self.assertFalse(CHECK.skip_tests_for_docs(hook_env(None)))

    def test_defaults_to_the_process_environment(self):
        with mock.patch.dict(os.environ, hook_env(["README.md"])):
            self.assertTrue(CHECK.skip_tests_for_docs())
        with mock.patch.dict(os.environ, hook_env(["a.py"])):
            self.assertFalse(CHECK.skip_tests_for_docs())


class RunTest(unittest.TestCase):
    def run_check(self, env):
        calls = []

        def fake_tests(root, opts):
            calls.append(root)
            return []

        out = io.StringIO()
        base = {k: v for k, v in os.environ.items() if not k.startswith("FACTORY_CH")}
        with mock.patch.dict(os.environ, {**base, **env}, clear=True), \
                mock.patch.object(CHECK, "CHECKS", [("tests", fake_tests)]), contextlib.redirect_stdout(out):
            code = CHECK.run(Path("."), Namespace(fast=False))
        return code, out.getvalue(), calls

    def test_docs_only_stop_hook_run_skips_the_tests_and_says_so(self):
        code, out, calls = self.run_check(hook_env(["README.md"]))
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertTrue(out.startswith("SKIP tests"), out)
        self.assertNotIn("PASS tests", out)

    def test_other_runs_call_the_tests(self):
        for env in ({}, hook_env(["a.py"]), hook_env(["README.md"], "ci")):
            with self.subTest(env=env):
                code, out, calls = self.run_check(env)
                self.assertEqual(code, 0)
                self.assertEqual(len(calls), 1)
                self.assertEqual(out, "PASS tests\n")

    def test_a_failing_test_stage_still_fails_when_it_runs(self):
        out = io.StringIO()
        with mock.patch.object(CHECK, "CHECKS", [("tests", lambda root, opts: ["boom"])]), \
                mock.patch.dict(os.environ, hook_env(["a.py"])), contextlib.redirect_stdout(out):
            self.assertEqual(CHECK.run(Path("."), Namespace(fast=False)), 1)

    def test_fast_still_skips_silently(self):
        out = io.StringIO()
        with mock.patch.object(CHECK, "CHECKS", [("tests", lambda root, opts: ["boom"])]), \
                contextlib.redirect_stdout(out):
            self.assertEqual(CHECK.run(Path("."), Namespace(fast=True)), 0)
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
