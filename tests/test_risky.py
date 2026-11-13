import contextlib
import importlib.machinery
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from budget_case import BudgetCase
from factory_project import FactoryProject, git

VENDOR_GATE = Path(__file__).resolve().parents[1] / "vendor/factory/factory/bin/gate"


class RiskyGateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        target = self.project.repo / "factory/bin/gate"
        target.write_bytes(VENDOR_GATE.read_bytes())
        loader = importlib.machinery.SourceFileLoader(f"gate_{id(self)}", str(target))
        self.gate = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(self.gate)
        self.wt = Path(tmp.name) / "wt"
        git(self.project.repo, "worktree", "add", "-q", "-b", "job", str(self.wt), "origin/main")

    def commit(self, files):
        for rel, text in files.items():
            (self.wt / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.wt / rel).write_text(text)
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "change")

    def test_path_matches_root_and_nested_double_star(self):
        m = self.gate.path_matches
        self.assertTrue(m("package.json", "**/package.json"))
        self.assertTrue(m("web/package.json", "**/package.json"))
        self.assertTrue(m(".github/workflows/ci.yml", ".github/workflows/**"))
        self.assertTrue(m("requirements-dev.txt", "**/requirements*.txt"))
        self.assertFalse(m("src/package.py", "**/package.json"))

    def test_lists_added_modified_and_deleted_risky_files(self):
        self.commit({"package.json": "{}\n", ".github/workflows/ci.yml": "on: push\n", "src/app.py": "x = 1\n"})
        hits = self.gate.risky_changes(self.wt, self.gate.CONFIG["risky_paths"])
        self.assertEqual(sorted(hits), ["A .github/workflows/ci.yml", "A package.json"])

    def test_old_config_without_risky_paths_lists_nothing(self):
        self.commit({"package.json": "{}\n"})
        self.assertEqual(self.gate.risky_changes(self.wt, self.gate.CONFIG.get("no-such-key", [])), [])


RISKY_CHECKS = ("GATE: PASS\nCOMMIT: abc\n\n## Summary\n- ok\n\n## Protected paths\nNone changed.\n\n"
                "## Risky changes\n- M package.json\n- A .github/workflows/ci.yml\n\n## checks.sh\nExit 0\n")


class RiskyMergeTest(BudgetCase):
    def approved(self, checks=RISKY_CHECKS):
        self.in_review()
        self.advance("approve")
        (self.d / "decision.md").write_text("APPROVE\n")
        (self.d / "round-1" / "checks.md").write_text(checks)

    def merge(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_merge(self.current())
        return out.getvalue()

    def test_risky_listed_reads_checks_md(self):
        self.approved()
        self.assertEqual(self.job.risky_listed(self.current()), ["M package.json", "A .github/workflows/ci.yml"])

    def test_merge_stops_without_risk_ok(self):
        self.approved()
        out = self.merge()
        job = self.current()
        self.assertEqual(job["stage"], "needs-human")
        self.assertTrue(job["risk_stopped"])
        self.assertIn("changes dependencies or CI: M package.json", (self.d / "decision.md").read_text())
        self.assertIn("factory:risk-ok", out)

    def test_risk_ok_label_resumes_and_moves_back_to_merging(self):
        self.approved()
        self.merge()
        self.issues = [{"number": 7, "title": "Build the widget"}]
        self.project.issue["labels"].append({"name": "factory:risk-ok"})
        queue = io.StringIO()
        with contextlib.redirect_stdout(queue):
            self.job.cmd_queue()
        self.assertIn("resume\t7", queue.getvalue())
        self.assertIn("factory:risk-ok added", queue.getvalue())
        job = self.advance("merging")
        self.assertEqual(job["stage"], "merging")
        self.assertNotIn("risk_stopped", job)

    def test_no_risk_ok_no_way_back_to_merging(self):
        self.approved()
        self.merge()
        with self.assertRaisesRegex(self.job.Refused, "add the factory:risk-ok label"):
            self.advance("merging")

    def test_other_needs_human_jobs_cannot_jump_to_merging(self):
        self.in_review()
        job = self.current()
        self.job.stop_for_human(job, "something else")
        with self.assertRaisesRegex(self.job.Refused, "only a job stopped for risky changes"):
            self.advance("merging")

    def test_no_risky_section_means_no_stop(self):
        self.approved(checks="GATE: PASS\n\n## Risky changes\nNone.\n")
        self.assertEqual(self.job.risky_listed(self.current()), [])

    def test_feedback_after_a_risk_stop_clears_it(self):
        self.approved()
        self.merge()
        (self.d / "feedback-1.md").write_text("# Feedback 1\n\nDrop the new dependency.\n")
        job = self.advance("build")
        self.assertNotIn("risk_stopped", job)
