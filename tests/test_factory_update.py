import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import factory_files as ff  # noqa: E402

PLAN = REPO / "bin/factory-update-plan"


class UpdatePlanTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vendor = Path(tmp.name) / "vendor"
        shutil.copytree(ff.VENDOR, self.vendor)
        self.project = Path(tmp.name) / "project"
        for rel in ff.FILES:
            target = self.project / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.vendor / rel, target)
        (self.project / ff.MANIFEST).write_text(json.dumps(ff.manifest_data(self.vendor)))

    def run_plan(self, *args):
        env = {**os.environ, "FACTORY_VENDOR_DIR": str(self.vendor)}
        res = subprocess.run([sys.executable, str(PLAN), str(self.project), *args],
                             capture_output=True, text=True, env=env)
        groups = dict(reversed(line.split("\t")) for line in res.stdout.splitlines() if "\t" in line)
        return res, groups

    def upstream(self, rel, text):
        (self.vendor / rel).write_text(text)

    def local(self, rel, text):
        (self.project / rel).write_text(text)

    def test_fresh_install_is_all_unchanged_except_special_files(self):
        res, groups = self.run_plan()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(groups["factory/checks.sh"], "owned")
        self.assertEqual(groups["factory/config.json"], "config")
        self.assertEqual(groups["factory/runner-settings.json"], "settings")
        self.assertEqual(groups["factory/bin/job"], "unchanged")

    def test_groups(self):
        self.upstream("factory/bin/route", "# upstream route\n")
        self.upstream("factory/bin/gate", "# upstream gate\n")
        self.local("factory/bin/gate", "# my gate\n")
        self.local(".claude/agents/reviewer-ui.md", "my tailored reviewer\n")
        (self.project / "factory/dashboard.html").unlink()
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/bin/route"], "safe")
        self.assertEqual(groups["factory/bin/gate"], "merge")
        self.assertEqual(groups[".claude/agents/reviewer-ui.md"], "unchanged")
        self.assertEqual(groups["factory/dashboard.html"], "new")

    def test_apply_safe(self):
        self.upstream("factory/bin/route", "# upstream route\n")
        (self.vendor / "factory/bin/route").chmod(0o755)
        self.upstream("factory/bin/gate", "# upstream gate\n")
        self.local("factory/bin/gate", "# my gate\n")
        self.upstream("factory/checks.sh", "# upstream checks\n")
        self.local("factory/checks.sh", "# my checks\n")
        (self.project / "factory/dashboard.html").unlink()
        res, _ = self.run_plan("--apply-safe")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.project / "factory/bin/route").read_text(), "# upstream route\n")
        self.assertTrue(os.access(self.project / "factory/bin/route", os.X_OK))
        self.assertEqual((self.project / "factory/bin/gate").read_text(), "# my gate\n")
        self.assertEqual((self.project / "factory/checks.sh").read_text(), "# my checks\n")
        self.assertTrue((self.project / "factory/dashboard.html").exists())

    def test_config_merge_adds_keys_and_keeps_values(self):
        cfg = json.loads((self.vendor / "factory/config.json").read_text())
        cfg["new_section"] = {"x": 1}
        cfg["budgets"]["new_limit"] = 5
        cfg["concurrency"] = 99
        (self.vendor / "factory/config.json").write_text(json.dumps(cfg))
        mine = json.loads((self.project / "factory/config.json").read_text())
        mine["concurrency"] = 1
        (self.project / "factory/config.json").write_text(json.dumps(mine))
        self.run_plan("--apply-safe")
        merged = json.loads((self.project / "factory/config.json").read_text())
        self.assertEqual(merged["concurrency"], 1)
        self.assertEqual(merged["new_section"], {"x": 1})
        self.assertEqual(merged["budgets"]["new_limit"], 5)

    def test_settings_keep_added_domains(self):
        path = "factory/runner-settings.json"
        new_rule = "Bash(sudo *)"
        mine = json.loads((self.project / path).read_text())
        mine["sandbox"]["network"]["allowedDomains"].append("registry.npmjs.org")
        (self.project / path).write_text(json.dumps(mine))
        upstream = json.loads((self.vendor / path).read_text())
        upstream["permissions"]["deny"].append(new_rule)
        (self.vendor / path).write_text(json.dumps(upstream))
        self.run_plan("--apply-safe")
        merged = json.loads((self.project / path).read_text())
        self.assertIn("registry.npmjs.org", merged["sandbox"]["network"]["allowedDomains"])
        self.assertIn("github.com", merged["sandbox"]["network"]["allowedDomains"])
        self.assertIn(new_rule, merged["permissions"]["deny"])

    def test_manifest_rewritten_after_apply(self):
        self.upstream("factory/bin/route", "# upstream route\n")
        self.run_plan("--apply-safe")
        manifest = json.loads((self.project / ff.MANIFEST).read_text())
        self.assertEqual(manifest, ff.manifest_data(self.vendor))
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/bin/route"], "unchanged")

    def test_without_manifest_differing_files_are_merge(self):
        (self.project / ff.MANIFEST).unlink()
        self.local("factory/bin/gate", "# my gate\n")
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/bin/gate"], "merge")
        self.assertEqual(groups["factory/bin/route"], "unchanged")

    def test_not_installed_refuses(self):
        (self.project / "factory/bin/job").unlink()
        res, _ = self.run_plan()
        self.assertEqual(res.returncode, 1)
        self.assertIn("run /factory-install first", res.stderr)

    def test_invalid_config_refuses_and_applies_nothing(self):
        self.upstream("factory/bin/route", "# upstream route\n")
        self.local("factory/config.json", "{not json")
        res, _ = self.run_plan("--apply-safe")
        self.assertEqual(res.returncode, 1)
        self.assertIn("factory/config.json", res.stderr)
        self.assertNotEqual((self.project / "factory/bin/route").read_text(), "# upstream route\n")


if __name__ == "__main__":
    unittest.main()
