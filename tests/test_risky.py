import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path

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
