import contextlib
import importlib.machinery
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from budget_case import BudgetCase
from factory_project import VENDOR, FactoryProject, git

# Built at runtime so no secret-looking literal sits in the repo.
SAMPLES = {
    "private key": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "aws access key": "AKIA" + "Q" * 16,
    "github token": "ghp_" + "a1" * 18,
    "anthropic key": "sk-" + "ant-" + "x" * 24,
    "slack token": "xox" + "b-" + "1" * 12,
    "assigned secret": "api_key = '" + "z" * 20 + "'",
}


class ScanCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        self.wt = Path(tmp.name) / "wt"
        git(self.project.repo, "worktree", "add", "-q", "-b", "factory/001-x", str(self.wt), "origin/main")

    def commit(self, files):
        for rel, text in files.items():
            (self.wt / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.wt / rel).write_text(text)
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "change")


class SecretScanTest(ScanCase):
    def test_each_rule_hits_and_masks_the_value(self):
        self.commit({"conf.py": "x = 1\n" + "\n".join(SAMPLES.values()) + "\n"})
        hits = self.job.secret_hits(self.wt)
        self.assertEqual([h.split(" ", 1)[1].split(":")[0] for h in hits], list(SAMPLES))
        self.assertTrue(hits[0].startswith("conf.py:2 "))
        for hit, value in zip(hits, SAMPLES.values()):
            self.assertNotIn(value, hit)
            self.assertIn("chars)", hit)

    def test_allow_globs_and_removed_lines_are_skipped(self):
        self.commit({"tests/fixtures/keys.txt": SAMPLES["aws access key"] + "\n",
                     "app.test.js": SAMPLES["github token"] + "\n"})
        self.assertEqual(self.job.secret_hits(self.wt), [])

    def test_push_refuses_on_a_hit_and_pushes_when_clean(self):
        job = {"id": "001-x", "stage": "build", "worktree": str(self.wt), "branch": "factory/001-x"}
        self.commit({"conf.py": SAMPLES["aws access key"] + "\n"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            self.job.cmd_push(job)
        self.assertIn("SECRET: conf.py:1 aws access key", out.getvalue())
        self.assertEqual(git(self.project.repo, "ls-remote", "origin", "factory/001-x"), "")
        self.commit({"conf.py": "key = load_from_env()\n"})
        git(self.wt, "reset", "-q", "--soft", "HEAD~2")
        git(self.wt, "commit", "-q", "-m", "clean")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_push(job)
        self.assertIn("PUSHED: factory/001-x", out.getvalue())
        self.assertNotEqual(git(self.project.repo, "ls-remote", "origin", "factory/001-x"), "")

    def test_gate_found_secrets_reads_checks_md(self):
        d = self.job.job_dir("001-x")
        (d / "round-1").mkdir(parents=True)
        job = {"id": "001-x", "round": 1}
        (d / "round-1" / "checks.md").write_text("GATE: FAIL\n\n## Secrets\nNone found.\n")
        self.assertFalse(self.job.gate_found_secrets(job))
        (d / "round-1" / "checks.md").write_text("GATE: FAIL\n\n## Secrets\n- conf.py:1 aws access key: AKIA… (20 chars)\n")
        self.assertTrue(self.job.gate_found_secrets(job))


class GateScanTest(ScanCase):
    """The gate runs `job scan` while `job merge` may hold the job's lock."""

    def setUp(self):
        super().setUp()
        target = self.project.repo / "factory/bin/gate"
        target.write_bytes((VENDOR / "factory/bin/gate").read_bytes())
        loader = importlib.machinery.SourceFileLoader(f"gate_{id(self)}", str(target))
        self.gate = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(self.gate)
        d = self.job.job_dir("001-x")
        d.mkdir(parents=True)
        (d / "job.json").write_text(json.dumps({"id": "001-x", "stage": "merging", "worktree": str(self.wt),
                                                "branch": "factory/001-x"}))

    def test_scan_runs_while_the_job_is_locked(self):
        self.commit({"conf.py": SAMPLES["aws access key"] + "\n"})
        self.job.load("001-x")  # holds the lock, as `job merge` does while the gate runs
        res = subprocess.run([sys.executable, str(self.project.repo / "factory/bin/job"), "scan", "001-x"],
                             cwd=self.project.repo, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("SECRET: conf.py:1 aws access key", res.stdout)

    def test_gate_reports_masked_hits(self):
        self.commit({"conf.py": SAMPLES["aws access key"] + "\n"})
        hits = self.gate.secret_scan("001-x")
        self.assertEqual([h.split(": ")[0] for h in hits], ["conf.py:1 aws access key"])
        self.assertNotIn(SAMPLES["aws access key"], hits[0])

    def test_gate_stops_when_the_scan_itself_fails(self):
        (self.job.job_dir("001-x") / "job.json").write_text(json.dumps({"id": "001-x", "worktree": "/nonexistent"}))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            self.gate.secret_scan("001-x")
        self.assertEqual(stop.exception.code, 2)


class GateSecretAdvanceTest(BudgetCase):
    def gate_failed_with_a_secret(self, round_limit=3):
        job = self.job.load(self.job_id)
        job.update({"stage": "gate", "round": 1, "round_limit": round_limit, "pr": 12})
        self.job.save(job)
        (self.d / "round-1").mkdir(exist_ok=True)
        (self.d / "round-1" / "checks.md").write_text(
            "GATE: FAIL\nCOMMIT: abc\n\n## Secrets\n- conf.py:1 aws access key: AKIA… (20 chars)\n")

    def test_a_secret_goes_to_needs_human_not_build(self):
        self.gate_failed_with_a_secret()
        job = self.advance("build")
        self.assertEqual(job["stage"], "needs-human")
        self.assertIn("Rotate it", (self.d / "decision.md").read_text())

    def test_a_secret_in_the_last_round_says_rotate_it(self):
        self.gate_failed_with_a_secret(round_limit=1)
        job = self.advance("needs-human")
        self.assertEqual(job["stage"], "needs-human")
        self.assertIn("Rotate it", (self.d / "decision.md").read_text())


class BuilderWordingTest(unittest.TestCase):
    def test_builder_pushes_through_job_push(self):
        text = (Path(__file__).resolve().parents[1] / "vendor/factory/.claude/agents/builder.md").read_text()
        self.assertIn("factory/bin/job push <job-id>", text)
        self.assertNotIn("git push -u origin <branch>", text)
