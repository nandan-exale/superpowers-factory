import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import FactoryProject, git  # noqa: E402


class SyncMainTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        other = Path(tmp.name) / "other"
        git(tmp.name, "clone", "-q", str(self.project.origin), str(other))
        git(other, "config", "user.email", "t@example.com")
        git(other, "config", "user.name", "T")
        (other / "merged.txt").write_text("from the PR\n")
        git(other, "add", "merged.txt")
        git(other, "commit", "-q", "-m", "merged PR")
        git(other, "push", "-q", "origin", "main")
        self.remote = git(other, "rev-parse", "HEAD")
        self.before = git(self.project.repo, "rev-parse", "HEAD")

    def sync(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.sync_main()
        return out.getvalue()

    def head(self):
        return git(self.project.repo, "rev-parse", "HEAD")

    def test_clean_main_is_fast_forwarded(self):
        out = self.sync()
        self.assertEqual(self.head(), self.remote)
        self.assertNotIn("NOTE", out)

    def test_untracked_files_do_not_block(self):
        (self.project.repo / "scratch.txt").write_text("x\n")
        self.sync()
        self.assertEqual(self.head(), self.remote)

    def test_other_branch_is_left_alone(self):
        git(self.project.repo, "checkout", "-q", "-b", "feature")
        out = self.sync()
        self.assertIn("NOTE: main checkout is on feature, not main; not pulled", out)
        self.assertEqual(self.head(), self.before)

    def test_local_changes_are_left_alone(self):
        spec = next(self.project.repo.glob("docs/superpowers/specs/*.md"))
        spec.write_text("edited\n")
        out = self.sync()
        self.assertIn("NOTE: main checkout has local changes; not pulled", out)
        self.assertEqual(self.head(), self.before)

    def test_diverged_main_is_left_alone(self):
        (self.project.repo / "local.txt").write_text("local\n")
        git(self.project.repo, "add", "local.txt")
        git(self.project.repo, "commit", "-q", "-m", "local")
        local = self.head()
        out = self.sync()
        self.assertIn("NOTE: main can't fast-forward to origin/main; not pulled", out)
        self.assertEqual(self.head(), local)


if __name__ == "__main__":
    unittest.main()
