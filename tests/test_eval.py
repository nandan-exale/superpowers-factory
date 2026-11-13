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


FAKE_CLAUDE = r'''
import json, os, subprocess, sys
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    sys.exit(int(os.environ.get("FAKE_AUTH_EXIT", "0")))
prompt = sys.stdin.read()
branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
with open(os.environ["FAKE_RECORD"], "a") as f:
    f.write(json.dumps({"argv": args, "prompt": prompt, "cwd": os.getcwd(), "branch": branch,
                        "files": sorted(os.listdir("."))}) + "\n")
out = os.environ.get("FAKE_OUT_REL")
if out:
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        f.write(os.environ.get("FAKE_TEXT", ""))
print(json.dumps({"total_cost_usd": float(os.environ.get("FAKE_COST", "0.10")), "result": "done"}))
'''


class RunTest(EvalCase):
    def setUp(self):
        super().setUp()
        self.ev.EVALS = self.tmp / "evals"
        self.ev.BASELINE = self.ev.EVALS / "baseline.json"
        case = self.ev.EVALS / "reviewer-code" / "off-by-one"
        (case / "files" / "src").mkdir(parents=True)
        (case / "files" / "src" / "a.py").write_text("x = 1\n")
        (case / "files" / "src" / "old.py").write_text("y = 2\n")
        (case / "change" / "src").mkdir(parents=True)
        (case / "change" / "src" / "a.py").write_text("x = 2\n")
        (case / "delete.txt").write_text("src/old.py\n")
        (case / "input.md").write_text("Job folder: {root}/factory/jobs/eval/. Review round 1.\n")
        (case / "expect.json").write_text(json.dumps(
            {"output": "factory/jobs/eval/round-1/review-code.md", "verdict": "CHANGES"}))
        fakebin = self.tmp / "bin"
        fakebin.mkdir()
        (fakebin / "claude").write_text(f"#!{sys.executable}\n{FAKE_CLAUDE}")
        (fakebin / "claude").chmod(0o755)
        self.record = self.tmp / "record.jsonl"
        self.env = {"PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}", "FAKE_RECORD": str(self.record),
                    "FAKE_OUT_REL": "factory/jobs/eval/round-1/review-code.md",
                    "FAKE_TEXT": "VERDICT: CHANGES\n\n## Findings\n1. [other:off-by-one] src/a.py:1 fix\n"}

    def main(self, *args, **env):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {**self.env, **env}), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(out):
            code = self.ev.main(list(args))
        return code, out.getvalue()

    def calls(self):
        return [json.loads(line) for line in self.record.read_text().splitlines()] if self.record.exists() else []

    def test_a_passing_case_runs_each_sample_in_a_fresh_workspace(self):
        code, out = self.main("--samples", "2")
        self.assertEqual(code, 0, out)
        self.assertIn("reviewer-code/off-by-one", out)
        first, second = self.calls()
        self.assertNotEqual(first["cwd"], second["cwd"])
        self.assertEqual(first["branch"], "factory/eval")
        self.assertIn(f"Job folder: {first['cwd']}/factory/jobs/eval/", first["prompt"])
        argv = first["argv"]
        model = self.cfg["routing"]["medium"]["code"]
        self.assertEqual(argv[argv.index("--model") + 1], model["model"])
        self.assertEqual(argv[argv.index("--effort") + 1], model["effort"])
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        allowed = argv[argv.index("--allowedTools") + 1].split(",")
        self.assertIn("Write(./**)", allowed)
        self.assertIn("Bash(git *)", allowed)
        self.assertNotIn("Bash", allowed)
        self.assertFalse(argv[argv.index("--append-system-prompt") + 1].startswith("---"))

    def test_workspace_has_the_change_and_the_deletion_on_a_branch(self):
        root = self.tmp / "ws"
        root.mkdir()
        self.ev.workspace(self.ev.EVALS / "reviewer-code" / "off-by-one", root)
        diff = subprocess.run(["git", "diff", "--name-status", "main...HEAD"], cwd=root,
                              capture_output=True, text=True, check=True).stdout
        self.assertEqual(sorted(diff.split("\n")[:-1]), ["D\tsrc/old.py", "M\tsrc/a.py"])
        self.assertTrue((root / "factory" / "config.json").is_file())
        self.assertTrue((root / "factory" / "jobs" / "eval" / "round-1").is_dir())

    def test_a_regression_fails_the_run(self):
        self.ev.BASELINE.write_text(json.dumps({"reviewer-code/off-by-one": 1.0}))
        code, out = self.main("--samples", "3", FAKE_TEXT="VERDICT: PASS\n")
        self.assertEqual(code, 1)
        self.assertIn("REGRESSION reviewer-code/off-by-one", out)

    def test_update_baseline_merges_new_rates(self):
        self.ev.BASELINE.write_text(json.dumps({"intake/accept": 0.67}))
        code, _ = self.main("--samples", "1", "--update-baseline")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.ev.BASELINE.read_text()),
                         {"intake/accept": 0.67, "reviewer-code/off-by-one": 1.0})

    def test_the_cap_stops_and_keeps_the_baseline(self):
        code, out = self.main("--samples", "3", "--max-usd", "0.5", "--update-baseline", FAKE_COST="0.4")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls()), 2)
        self.assertIn("spend cap", out)
        self.assertFalse(self.ev.BASELINE.exists())

    def test_logged_out_claude_exits_2(self):
        code, out = self.main(FAKE_AUTH_EXIT="1")
        self.assertEqual(code, 2)
        self.assertIn("claude auth login", out)

    def test_an_invalid_case_exits_2_before_any_call(self):
        (self.ev.EVALS / "reviewer-code" / "off-by-one" / "input.md").unlink()
        code, out = self.main()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.calls(), [])
