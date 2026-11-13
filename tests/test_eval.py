import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script_loader import load_script

PLUGIN = Path(__file__).resolve().parents[1]


class EvalCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ev = load_script(PLUGIN / "scripts" / "eval", f"eval_{id(self)}")
        self.cfg = json.loads(self.ev.CONFIG.read_text())


class AgentTest(EvalCase):
    def test_agent_prompt_drops_frontmatter_and_reads_tools(self):
        body, tools = self.ev.agent_prompt("intake")
        self.assertEqual(tools, ["Read", "Grep", "Glob", "Write"])
        self.assertFalse(body.startswith("---"))
        self.assertIn("DECISION: ACCEPT", body)

    def test_unknown_agent_stops(self):
        with self.assertRaisesRegex(self.ev.Stop, "no agent 'nope'"):
            self.ev.agent_prompt("nope")

    def test_model_for_each_kind_of_agent(self):
        self.assertEqual(self.ev.model_for("intake", self.cfg), self.cfg["agents"]["intake"])
        self.assertEqual(self.ev.model_for("reviewer-code", self.cfg), self.cfg["routing"]["medium"]["code"])
        self.assertEqual(self.ev.model_for("approver", self.cfg), self.cfg["routing"]["medium"]["approver"])
        self.assertEqual(self.ev.model_for("reviewer-security", self.cfg),
                         self.cfg["surface_reviewers"]["security"]["security"])
        with self.assertRaisesRegex(self.ev.Stop, "no model"):
            self.ev.model_for("reviewer-nope", self.cfg)


REVIEW = "VERDICT: CHANGES\n\n## Findings\n1. [missing-test] a.py:1 add one\n2. [other:x] b\n\n## Notes\n1. [secrets] no\n"


class CheckTest(EvalCase):
    def test_each_expectation(self):
        check = self.ev.check
        self.assertEqual(check({"verdict": "CHANGES", "tags_any": ["other:*"]}, REVIEW), [])
        self.assertEqual(len(check({"verdict": "PASS"}, REVIEW)), 1)
        self.assertEqual(len(check({"tags_any": ["secrets"]}, REVIEW)), 1)
        self.assertEqual(check({"first_line": "DECISION: REJECT"}, "\nDECISION: REJECT\nRISK: low\n"), [])
        self.assertEqual(len(check({"first_line": "DECISION: REJECT"}, "DECISION: ACCEPT\n")), 1)
        self.assertEqual(check({"regex": r"^RISK: (low|medium)$"}, "DECISION: X\nRISK: low\n"), [])

    def test_validate_case(self):
        d = self.tmp / "case"
        d.mkdir()
        (d / "expect.json").write_text(json.dumps({"output": "x.md", "bogus": 1}))
        problems = self.ev.validate_case(d)
        self.assertEqual(len(problems), 3, problems)  # no input.md, unknown key, checks nothing


class BaselineTest(EvalCase):
    def test_a_case_fails_only_when_more_than_one_sample_below(self):
        baseline = {"a/x": 1.0, "a/y": 1.0}
        rates = {"a/x": 2 / 3, "a/y": 1 / 3, "a/new": 0.0}
        self.assertEqual(self.ev.regressions(rates, baseline, 3), ["a/y"])
