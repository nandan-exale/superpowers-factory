import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from factory_project import FactoryProject, git


class UpdateBranchTest(unittest.TestCase):
    """job update-branch merges origin/<base> into a job worktree from the orchestrator's process,
    where the agent sandbox's write denies on factory files don't apply."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.repo = self.project.repo
        self.commit_on_main({"factory/runner-settings.json": "{}\n", "app.txt": "one\n"}, "settings")
        self.job = self.project.load_job()
        self.project.set_issue("Build the widget.", labels=("factory",))
        self.id = self.project.create_job(self.job)
        job = self.job.load(self.id)
        job["stage"], job["round"] = "build", 2
        self.job.save(job)
        self.wt = Path(job["worktree"])
        git(self.repo, "worktree", "add", "-q", "-b", job["branch"], str(self.wt), "origin/main")

    def commit_on_main(self, files, message):
        for rel, text in files.items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            git(self.repo, "add", rel)
        git(self.repo, "commit", "-q", "-m", message)
        git(self.repo, "push", "-q", "origin", "main")

    def commit_on_branch(self, files, message):
        for rel, text in files.items():
            (self.wt / rel).write_text(text)
            git(self.wt, "add", rel)
        git(self.wt, "commit", "-q", "-m", message)

    def update(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_update_branch(self.job.load(self.id))
        return out.getvalue()

    def stage(self):
        return json.loads((self.job.job_dir(self.id) / "job.json").read_text())["stage"]

    def merging(self):
        return (Path(git(self.wt, "rev-parse", "--absolute-git-dir")) / "MERGE_HEAD").exists()

    def test_base_change_to_a_sandbox_denied_file_is_merged(self):
        # Job 016: main changed factory/runner-settings.json and the builder's sandboxed merge couldn't
        # replace it. The factory merges it instead.
        self.commit_on_branch({"work.txt": "work\n"}, "work")
        self.commit_on_main({"factory/runner-settings.json": '{"sandbox": {}}\n'}, "settings change")
        out = self.update()
        self.assertIn(f"UPDATE-BRANCH: {self.id} merged origin/main", out)
        self.assertEqual((self.wt / "factory/runner-settings.json").read_text(), '{"sandbox": {}}\n')
        self.assertEqual(len(git(self.wt, "rev-list", "--parents", "-n1", "HEAD").split()), 3)
        self.assertFalse(self.merging())
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")
        self.assertEqual(self.stage(), "build")

    def test_conflict_in_an_unprotected_file_is_left_for_the_builder(self):
        self.commit_on_branch({"app.txt": "branch\n"}, "branch edit")
        self.commit_on_main({"app.txt": "main\n", "factory/runner-settings.json": '{"x": 1}\n'}, "main edit")
        out = self.update()
        self.assertIn(f"UPDATE-BRANCH: {self.id} conflicts: app.txt", out)
        self.assertTrue(self.merging())
        # Git wrote the base's side of everything that didn't conflict, protected or not.
        self.assertEqual((self.wt / "factory/runner-settings.json").read_text(), '{"x": 1}\n')
        self.assertEqual(self.stage(), "build")

    def test_conflict_in_a_protected_file_aborts_and_escalates(self):
        self.commit_on_branch({"factory/config.json": "{}\n"}, "human edit")
        self.commit_on_main({"factory/config.json": '{"a": 1}\n'}, "main edit")
        head = git(self.wt, "rev-parse", "HEAD")
        out = self.update()
        self.assertIn("needs-human", out)
        self.assertEqual(self.stage(), "needs-human")
        self.assertIn("factory/config.json", (self.job.job_dir(self.id) / "decision.md").read_text())
        self.assertFalse(self.merging())
        self.assertEqual(git(self.wt, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")

    def test_up_to_date_branch_is_left_alone(self):
        self.commit_on_branch({"work.txt": "work\n"}, "work")
        head = git(self.wt, "rev-parse", "HEAD")
        self.assertIn(f"UPDATE-BRANCH: {self.id} up to date", self.update())
        self.assertEqual(git(self.wt, "rev-parse", "HEAD"), head)

    def test_uncommitted_changes_are_never_merged_over(self):
        self.commit_on_main({"other.txt": "main\n"}, "main edit")
        (self.wt / "app.txt").write_text("unfinished\n")
        head = git(self.wt, "rev-parse", "HEAD")
        out = self.update()
        self.assertIn(f"UPDATE-BRANCH: {self.id} skipped", out)
        self.assertIn("NOTE:", out)
        self.assertEqual(git(self.wt, "rev-parse", "HEAD"), head)
        self.assertEqual((self.wt / "app.txt").read_text(), "unfinished\n")

    def test_a_merge_in_progress_is_left_for_the_builder(self):
        self.commit_on_branch({"app.txt": "branch\n"}, "branch edit")
        self.commit_on_main({"app.txt": "main\n"}, "main edit")
        self.update()
        self.assertIn(f"UPDATE-BRANCH: {self.id} merge in progress", self.update())
        self.assertTrue(self.merging())


if __name__ == "__main__":
    unittest.main()
