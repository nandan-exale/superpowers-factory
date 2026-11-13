import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from factory_project import FactoryProject, git

FAILED = [{"workflowName": "ci", "url": "https://github.com/o/r/actions/runs/1", "conclusion": "failure"}]


class RevertCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        self.calls = []

        def fake_gh(*args):
            self.calls.append(args)
            if args[:2] == ("pr", "create"):
                return "https://github.com/o/r/pull/44\n"
            return ""

        self.job.gh = fake_gh
        self.job.gh_json = lambda *args: {"commits": [{}, {}]}

    def land(self, merge_commit):
        """Put a 'PR' on origin/main, the way GitHub would merge it; returns the sha that landed."""
        repo = self.project.repo
        git(repo, "checkout", "-q", "-b", "feature")
        (repo / "widget.txt").write_text("spins\n")
        git(repo, "add", "widget.txt")
        git(repo, "commit", "-q", "-m", "add widget")
        git(repo, "checkout", "-q", "main")
        if merge_commit:
            git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #12", "feature")
        else:
            git(repo, "merge", "-q", "--squash", "feature")
            git(repo, "commit", "-q", "-m", "Add widget (#12)")
        git(repo, "push", "-q", "origin", "main")
        return git(repo, "rev-parse", "HEAD")

    def job_record(self, sha):
        return {"id": "001-widget", "issue": 7, "pr": 12, "title": "Add widget",
                "watch": {"sha": sha, "since": "2026-11-13T00:00:00Z", "state": "watching"}}

    def revert_branch_files(self):
        git(self.project.repo, "fetch", "-q", "origin")
        return git(self.project.repo, "ls-tree", "--name-only", "origin/factory/revert-001-widget")


class OpenRevertTest(RevertCase):
    def test_squash_merge_is_reverted_on_a_new_branch(self):
        self.job.CONFIG["merge_method"] = "squash"
        sha = self.land(merge_commit=False)
        self.assertEqual(self.job.open_revert_pr(self.job_record(sha), FAILED), 44)
        self.assertNotIn("widget.txt", self.revert_branch_files())
        create = next(c for c in self.calls if c[:2] == ("pr", "create"))
        self.assertIn('Revert "Add widget"', create)
        self.assertIn("factory:revert", create)
        self.assertFalse((self.project.repo / ".worktrees" / "revert-001-widget").exists())

    def test_merge_commit_is_reverted_with_mainline_1(self):
        self.job.CONFIG["merge_method"] = "merge"
        sha = self.land(merge_commit=True)
        self.job.open_revert_pr(self.job_record(sha), FAILED)
        self.assertNotIn("widget.txt", self.revert_branch_files())

    def test_a_conflict_opens_nothing(self):
        self.job.CONFIG["merge_method"] = "squash"
        sha = self.land(merge_commit=False)
        (self.project.repo / "widget.txt").write_text("spins faster\n")
        git(self.project.repo, "commit", "-qam", "later change")
        git(self.project.repo, "push", "-q", "origin", "main")
        with self.assertRaisesRegex(self.job.Refused, "didn't apply cleanly"):
            self.job.open_revert_pr(self.job_record(sha), FAILED)
        self.assertFalse(any(c[:2] == ("pr", "create") for c in self.calls))

    def test_revert_command_per_method(self):
        rc = self.job.revert_command
        self.assertEqual(rc("merge", "abc", 1), ["revert", "--no-edit", "-m", "1", "abc"])
        self.assertEqual(rc("squash", "abc", 1), ["revert", "--no-edit", "abc"])
        self.assertEqual(rc("rebase", "abc", 3), ["revert", "--no-edit", "abc~3..abc"])


class RevertForTest(RevertCase):
    def test_red_pauses_comments_labels_and_records(self):
        self.job.CONFIG["merge_method"] = "squash"
        sha = self.land(merge_commit=False)
        self.project.set_issue("Build the widget.", labels=("factory",))
        job_id = self.project.create_job(self.job)
        job = self.job.load(job_id)
        job.update(self.job_record(sha))
        job["id"] = job_id
        self.job.save(job)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.revert_for(self.job.load(job_id), FAILED)
        p = self.job.paused()
        self.assertEqual((p["reason"], p["sha"]), ("main failed after #12 (ci)", sha))
        saved = json.loads((self.job.job_dir(job_id) / "job.json").read_text())
        self.assertEqual((saved["watch"]["state"], saved["watch"]["revert_pr"]), ("red", 44))
        comments = [c for c in self.calls if c[1] == "comment"]
        self.assertEqual({c[0] for c in comments}, {"pr", "issue"})
        self.assertIn("factory/bin/job resume", comments[0][-1])
        self.assertIn(f"WATCH: {job_id} red", out.getvalue())
