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

    def make_git_project(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "FACTORY_", "CLAUDE_"))}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        for args in (("init", "-q"), ("remote", "add", "origin", "https://github.com/o/r.git")):
            subprocess.run(["git", *args], cwd=self.project, env=env, check=True, capture_output=True)

    def hook_text(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "FACTORY_", "CLAUDE_"))}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", CLAUDE_PROJECT_DIR=str(self.project),
                   FACTORY_VENDOR_DIR=str(self.vendor))
        res = subprocess.run([sys.executable, str(REPO / "hooks/factory-session")], input="{}",
                             capture_output=True, text=True, env=env)
        return json.loads(res.stdout)["hookSpecificOutput"]["additionalContext"] if res.stdout else ""

    def settings_json(self, root):
        return json.loads((root / "factory/runner-settings.json").read_text())

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

    def pending_merge(self):
        self.upstream("factory/bin/gate", "# upstream gate\n")
        self.local("factory/bin/gate", "# my gate\n")
        self.upstream("factory/bin/route", "# upstream route\n")
        self.make_git_project()

    def test_pending_merge_survives_apply_safe(self):
        self.pending_merge()
        self.run_plan("--apply-safe")
        manifest = json.loads((self.project / ff.MANIFEST).read_text())
        self.assertNotEqual(manifest["vendor_hash"], ff.vendor_hash(self.vendor))
        self.assertEqual(manifest["files"]["factory/bin/gate"],
                         ff.sha256_file(ff.VENDOR / "factory/bin/gate"))
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/bin/gate"], "merge")
        self.assertEqual(groups["factory/bin/route"], "unchanged")
        self.assertIn("/factory-update", self.hook_text())

    def test_pending_merge_without_old_entry_is_omitted_and_pending(self):
        (self.project / ff.MANIFEST).unlink()
        self.local("factory/bin/gate", "# my gate\n")
        self.run_plan("--apply-safe")
        manifest = json.loads((self.project / ff.MANIFEST).read_text())
        self.assertNotIn("factory/bin/gate", manifest["files"])
        self.assertEqual(manifest["vendor_hash"], "pending")
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/bin/gate"], "merge")

    def test_resolved_records_the_decision(self):
        self.pending_merge()
        self.run_plan("--apply-safe")
        res, _ = self.run_plan("--resolved", "factory/bin/gate")
        self.assertEqual(res.returncode, 0, res.stderr)
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/bin/gate"], "unchanged")
        self.assertEqual((self.project / "factory/bin/gate").read_text(), "# my gate\n")
        manifest = json.loads((self.project / ff.MANIFEST).read_text())
        self.assertEqual(manifest["vendor_hash"], ff.vendor_hash(self.vendor))
        self.assertNotIn("/factory-update", self.hook_text())

    def test_resolved_keeps_the_update_pending_while_merges_remain(self):
        self.pending_merge()
        self.upstream("factory/bin/job", "# upstream job\n")
        self.local("factory/bin/job", "# my job\n")
        self.run_plan("--apply-safe")
        self.run_plan("--resolved", "factory/bin/gate")
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/bin/job"], "merge")
        self.assertIn("/factory-update", self.hook_text())
        self.run_plan("--resolved", "factory/bin/job")
        self.assertNotIn("/factory-update", self.hook_text())

    def test_resolved_rejects_unknown_paths(self):
        res, _ = self.run_plan("--resolved", "README.md")
        self.assertEqual(res.returncode, 1)
        self.assertIn("README.md", res.stderr)

    def test_project_copy_equal_to_upstream_is_unchanged(self):
        self.upstream("factory/bin/gate", "# upstream gate\n")
        self.local("factory/bin/gate", "# upstream gate\n")
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/bin/gate"], "unchanged")
        (self.project / ff.MANIFEST).unlink()
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/bin/gate"], "unchanged")

    def test_settings_with_only_added_domains_stay_settings(self):
        mine = self.settings_json(self.project)
        mine["sandbox"]["network"]["allowedDomains"].append("registry.npmjs.org")
        (self.project / "factory/runner-settings.json").write_text(json.dumps(mine))
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/runner-settings.json"], "settings")

    def test_settings_changed_on_both_sides_is_a_merge(self):
        mine = self.settings_json(self.project)
        mine["permissions"]["deny"].append("Bash(sudo *)")
        (self.project / "factory/runner-settings.json").write_text(json.dumps(mine))
        theirs = self.settings_json(self.vendor)
        theirs["permissions"]["deny"].append("Bash(su *)")
        (self.vendor / "factory/runner-settings.json").write_text(json.dumps(theirs))
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/runner-settings.json"], "merge")
        before = (self.project / "factory/runner-settings.json").read_text()
        self.run_plan("--apply-safe")
        self.assertEqual((self.project / "factory/runner-settings.json").read_text(), before)
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/runner-settings.json"], "merge")
        self.run_plan("--resolved", "factory/runner-settings.json")
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/runner-settings.json"], "unchanged")

    def test_user_settings_rule_with_unchanged_upstream_is_kept(self):
        mine = self.settings_json(self.project)
        mine["permissions"]["deny"].append("Bash(sudo *)")
        (self.project / "factory/runner-settings.json").write_text(json.dumps(mine))
        before = (self.project / "factory/runner-settings.json").read_text()
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/runner-settings.json"], "unchanged")
        self.run_plan("--apply-safe")
        self.assertEqual((self.project / "factory/runner-settings.json").read_text(), before)

    def test_settings_without_manifest_core_differing_is_a_merge(self):
        (self.project / ff.MANIFEST).unlink()
        mine = self.settings_json(self.project)
        mine["permissions"]["deny"].append("Bash(sudo *)")
        (self.project / "factory/runner-settings.json").write_text(json.dumps(mine))
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/runner-settings.json"], "merge")

    def test_malformed_settings_shapes_refuse_and_apply_nothing(self):
        path = "factory/runner-settings.json"
        self.upstream("factory/bin/route", "# upstream route\n")
        for side, bad in (("project", {"sandbox": []}),
                          ("project", {"sandbox": {"network": {"allowedDomains": "github.com"}}}),
                          ("project", {"sandbox": {"network": {"allowedDomains": [1]}}}),
                          ("vendor", {"sandbox": {"network": []}})):
            with self.subTest(side=side, bad=bad):
                root = self.project if side == "project" else self.vendor
                good = (root / path).read_text()
                (root / path).write_text(json.dumps(bad))
                res, _ = self.run_plan("--apply-safe")
                self.assertEqual(res.returncode, 1, res.stdout)
                self.assertIn(path, res.stderr)
                self.assertNotEqual((self.project / "factory/bin/route").read_text(), "# upstream route\n")
                (root / path).write_text(good)

    def test_non_ascii_values_round_trip(self):
        cfg = json.loads((self.vendor / "factory/config.json").read_text())
        cfg["new_section"] = {"greeting": "caf\u00e9 \u2713"}
        (self.vendor / "factory/config.json").write_text(json.dumps(cfg))
        mine = json.loads((self.project / "factory/config.json").read_text())
        mine["note"] = "n\u00e4chste"
        (self.project / "factory/config.json").write_text(json.dumps(mine, ensure_ascii=False), encoding="utf-8")
        res, _ = self.run_plan("--apply-safe")
        self.assertEqual(res.returncode, 0, res.stderr)
        text = (self.project / "factory/config.json").read_text(encoding="utf-8")
        self.assertIn("n\u00e4chste", text)
        self.assertIn("caf\u00e9 \u2713", text)
        merged = json.loads(text)
        self.assertEqual(merged["note"], "n\u00e4chste")
        self.assertEqual(merged["new_section"], {"greeting": "caf\u00e9 \u2713"})

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
