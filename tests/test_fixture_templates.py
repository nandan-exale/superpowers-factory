"""The fixtures copy a template built once per process; each copy must still be its own project."""

import tempfile
import unittest
from pathlib import Path

from factory_project import FactoryProject, git
from installed_project import InstalledProject
from installed_project import git as clean_git


class FactoryProjectTemplateTest(unittest.TestCase):
    def setUp(self):
        a, b = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
        self.addCleanup(a.cleanup)
        self.addCleanup(b.cleanup)
        self.a, self.b = FactoryProject(a.name), FactoryProject(b.name)

    def test_origin_is_the_copy_s_own(self):
        url = git(self.a.repo, "remote", "get-url", "origin")
        self.assertEqual(Path(url).resolve(), self.a.origin)

    def test_a_push_reaches_only_its_own_origin(self):
        (self.a.repo / "x.txt").write_text("x\n")
        git(self.a.repo, "add", "x.txt")
        git(self.a.repo, "commit", "-q", "-m", "x")
        git(self.a.repo, "push", "-q", "origin", "main")
        self.assertNotEqual(git(self.a.origin, "rev-parse", "main"), git(self.b.origin, "rev-parse", "main"))
        self.assertEqual(git(self.b.origin, "rev-parse", "main"), self.b.sha)

    def test_main_tracks_origin(self):
        self.assertEqual(git(self.a.repo, "rev-parse", "--abbrev-ref", "main@{upstream}"), "origin/main")


class InstalledProjectTemplateTest(unittest.TestCase):
    def project(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return InstalledProject(tmp.name, **kw)

    def test_copies_are_independent(self):
        a, b = self.project(), self.project()
        a.write("only-a.txt", "a\n")
        a.commit_all("a")
        self.assertFalse((b.root / "only-a.txt").exists())
        self.assertEqual(clean_git(b.root, "log", "--format=%s").split(), ["install"])

    def test_helpers_live_beside_the_copy(self):
        p = self.project()
        self.assertTrue((p.fakebin / "gh").is_file())
        self.assertTrue((p.toolbin / "security").is_file())
        self.assertTrue(p.labels_file.is_file())

    def test_uncommitted_install_has_no_commit_and_a_staged_tree(self):
        p = self.project(commit=False)
        self.assertNotEqual(clean_git(p.root, "diff", "--cached", "--name-only"), "")
        with self.assertRaises(Exception):
            clean_git(p.root, "rev-parse", "HEAD")


if __name__ == "__main__":
    unittest.main()
