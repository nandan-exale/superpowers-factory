import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "vendor" / "factory" / "factory" / "lib"))

from orchestrator import readonly  # noqa: E402


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class ReadOnlyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.tree = root / "wt"
        self.tree.mkdir()
        git(self.tree, "init", "-q")
        git(self.tree, "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "x")
        self.folder = root / "job"
        (self.folder / "round-1").mkdir(parents=True)
        (self.folder / "job.json").write_text("{}")
        self.before = readonly.snapshot(self.folder, self.tree, compare_head=True)

    def after(self):
        return readonly.snapshot(self.folder, self.tree, compare_head=True)

    def test_own_file_and_bookkeeping_are_fine(self):
        (self.folder / "round-1" / "review-code.md").write_text("VERDICT: PASS\n")
        (self.folder / "job.json").write_text('{"x": 1}')
        (self.folder / "runs").mkdir()
        (self.folder / "runs" / "001-reviewer-code.json").write_text("{}")
        self.assertEqual(readonly.violations(self.before, self.after(), {"round-1/review-code.md"}), [])

    def test_another_file_in_the_job_folder(self):
        (self.folder / "spec.md").write_text("rewritten")
        problems = readonly.violations(self.before, self.after(), {"round-1/review-code.md"})
        self.assertEqual(problems, ["wrote files it doesn't own: spec.md"])

    def test_worktree_change(self):
        (self.tree / "new.py").write_text("x")
        problems = readonly.violations(self.before, self.after(), set())
        self.assertEqual(len(problems), 1)
        self.assertIn("changed the checkout", problems[0])
        self.assertIn("new.py", problems[0])

    def test_head_ignored_for_the_main_checkout(self):
        before = readonly.snapshot(self.folder, self.tree, compare_head=False)
        git(self.tree, "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "y")
        self.assertEqual(readonly.violations(before, readonly.snapshot(self.folder, self.tree, compare_head=False),
                                             set()), [])

    def test_quarantine_moves_own_files_into_runs(self):
        (self.folder / "round-1" / "review-code.md").write_text("VERDICT: PASS\n")
        readonly.quarantine(self.folder, {"round-1/review-code.md", "decision.md"})
        self.assertFalse((self.folder / "round-1" / "review-code.md").exists())
        self.assertTrue((self.folder / "runs" / "round-1--review-code.md.rejected").exists())


if __name__ == "__main__":
    unittest.main()
