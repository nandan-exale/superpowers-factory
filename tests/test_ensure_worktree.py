import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from factory_project import FactoryProject, git


class EnsureWorktreeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        self.project.set_issue("Build the widget.", labels=("factory",))
        self.id = self.project.create_job(self.job)

    def set_stage(self, stage):
        job = self.job.load(self.id)
        job["stage"] = stage
        self.job.save(job)
        return job

    def ensure(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_ensure_worktree(self.job.load(self.id))
        return out.getvalue()

    def test_recreated_from_the_pushed_branch(self):
        job = self.set_stage("build")
        git(self.project.repo, "worktree", "add", "-q", "-b", job["branch"], job["worktree"], "origin/main")
        (Path(job["worktree"]) / "w.txt").write_text("work\n")
        git(job["worktree"], "add", "w.txt")
        git(job["worktree"], "commit", "-q", "-m", "work")
        git(job["worktree"], "push", "-q", "origin", job["branch"])
        pushed = git(job["worktree"], "rev-parse", "HEAD")
        git(self.project.repo, "worktree", "remove", "--force", job["worktree"])
        git(self.project.repo, "branch", "-D", job["branch"])
        self.assertIn(f"recreated from origin/{job['branch']}", self.ensure())
        self.assertEqual(git(job["worktree"], "rev-parse", "HEAD"), pushed)

    def test_created_from_base_when_the_branch_was_never_pushed(self):
        job = self.set_stage("spec")
        self.assertIn("created from origin/main", self.ensure())
        self.assertEqual(git(job["worktree"], "rev-parse", "HEAD"), self.project.sha)

    def test_present_and_stages_without_a_worktree_are_left_alone(self):
        self.assertIn("not needed", self.ensure())  # intake
        job = self.set_stage("build")
        Path(job["worktree"]).mkdir(parents=True)
        self.assertIn("present", self.ensure())

    def test_git_failure_sends_the_job_to_needs_human(self):
        self.set_stage("build")
        shutil.rmtree(self.project.repo / ".worktrees", ignore_errors=True)
        (self.project.repo / ".worktrees").write_text("a file where the worktrees directory should be")
        out = self.ensure()
        self.assertIn("needs-human", out)
        self.assertEqual(json.loads((self.job.job_dir(self.id) / "job.json").read_text())["stage"], "needs-human")
