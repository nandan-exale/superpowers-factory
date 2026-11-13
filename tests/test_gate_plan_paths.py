import importlib.machinery
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import FactoryProject, git  # noqa: E402

VENDOR_GATE = Path(__file__).resolve().parents[1] / "vendor/factory/factory/bin/gate"
SPEC = "docs/superpowers/specs/2026-11-12-widget-design.md"
PLAN = "docs/superpowers/plans/2026-11-12-widget.md"


class GatePlanPathsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        target = self.project.repo / "factory/bin/gate"
        target.write_bytes(VENDOR_GATE.read_bytes())
        loader = importlib.machinery.SourceFileLoader(f"gate_{id(self)}", str(target))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.gate = importlib.util.module_from_spec(spec)
        loader.exec_module(self.gate)
        self.wt = Path(tmp.name) / "wt"
        git(self.project.repo, "worktree", "add", "-q", "-b", "job", str(self.wt), "origin/main")

    def commit(self, rel, text):
        (self.wt / rel).write_text(text)
        git(self.wt, "add", rel)
        git(self.wt, "-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-q", "-m", "x")

    def test_planned_job_patterns_include_its_spec_and_plan(self):
        patterns = self.gate.protected_patterns({"plan_paths": [SPEC, PLAN]})
        self.assertIn(SPEC, patterns)
        self.assertIn(PLAN, patterns)
        self.assertIn("factory/checks.sh", patterns)

    def test_unplanned_job_patterns_are_the_config_ones(self):
        self.assertEqual(self.gate.protected_patterns({}), self.gate.CONFIG["protected_paths"])

    def test_editing_the_plan_is_a_protected_change(self):
        self.commit(PLAN, "# rewritten\n")
        hits = self.gate.protected_changes(str(self.wt), self.gate.protected_patterns({"plan_paths": [SPEC, PLAN]}))
        self.assertEqual(hits, [f"M {PLAN}"])

    def test_editing_the_plan_is_fine_for_an_unplanned_job(self):
        self.commit(PLAN, "# rewritten\n")
        self.assertEqual(self.gate.protected_changes(str(self.wt), self.gate.protected_patterns({})), [])


if __name__ == "__main__":
    unittest.main()
