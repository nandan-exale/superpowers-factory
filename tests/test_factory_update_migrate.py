import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
sys.path.insert(0, str(REPO / "tests"))

import factory_files as ff  # noqa: E402
from installed_project import InstalledProject  # noqa: E402

PLAN = REPO / "bin/factory-update-plan"
OLD_CONFIG = REPO / "tests/fixtures/config-pre-0.2.0.json"


class MigrateOldConfigTest(unittest.TestCase):
    """A project installed before 0.2.0 keeps strings where {model, effort} is now expected."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p = InstalledProject(tmp.name)
        shutil.copy2(OLD_CONFIG, self.p.root / "factory/config.json")

    def plan(self, *args):
        return subprocess.run([sys.executable, str(PLAN), str(self.p.root), *args],
                              capture_output=True, text=True)

    def config(self):
        return json.loads((self.p.root / "factory/config.json").read_text())

    def test_apply_safe_migrates_strings_and_keeps_the_projects_models(self):
        res = self.plan("--apply-safe")
        self.assertEqual(res.returncode, 0, res.stderr)
        cfg = self.config()
        upstream = json.loads((ff.VENDOR / "factory/config.json").read_text())
        for risk in ("low", "medium", "high"):
            self.assertEqual(cfg["routing"][risk]["code"],
                             {"model": "haiku", "effort": upstream["routing"][risk]["code"]["effort"]})
        self.assertEqual(cfg["surface_reviewers"]["ui"]["ux"]["model"], "haiku")
        self.assertEqual(cfg["surface_reviewers"]["security"]["security"]["model"], "haiku")
        self.assertEqual(cfg["surface_reviewers"]["ui"]["ux"]["effort"],
                         upstream["surface_reviewers"]["ui"]["ux"]["effort"])

    def test_string_with_an_unknown_model_takes_upstreams_model(self):
        mine = json.loads(OLD_CONFIG.read_text())
        mine["routing"]["low"]["code"] = "gpt"
        (self.p.root / "factory/config.json").write_text(json.dumps(mine))
        self.plan("--apply-safe")
        upstream = json.loads((ff.VENDOR / "factory/config.json").read_text())
        self.assertEqual(self.config()["routing"]["low"]["code"], upstream["routing"]["low"]["code"])

    def test_dict_missing_effort_is_completed(self):
        mine = json.loads(OLD_CONFIG.read_text())
        mine["routing"]["low"]["code"] = {"model": "haiku"}
        (self.p.root / "factory/config.json").write_text(json.dumps(mine))
        self.plan("--apply-safe")
        entry = self.config()["routing"]["low"]["code"]
        self.assertEqual(entry["model"], "haiku")
        self.assertIn(entry["effort"], ff_efforts())

    def test_new_roles_come_from_upstream_defaults_and_are_reported(self):
        # The pre-0.2.0 file only routed `code`; spec-writer, builder and approver are new keys,
        # so they get upstream's defaults. The update says so instead of doing it silently.
        res = self.plan("--apply-safe")
        upstream = json.loads((ff.VENDOR / "factory/config.json").read_text())
        self.assertEqual(self.config()["routing"]["low"]["builder"], upstream["routing"]["low"]["builder"])
        self.assertIn("routing.low.builder", res.stdout)

    def test_unknown_model_replacement_is_reported_with_the_old_value(self):
        mine = json.loads(OLD_CONFIG.read_text())
        mine["routing"]["low"]["code"] = "gpt"
        (self.p.root / "factory/config.json").write_text(json.dumps(mine))
        res = self.plan("--apply-safe")
        self.assertIn("routing.low.code (was gpt)", res.stdout)

    def test_whole_added_tables_are_listed(self):
        mine = json.loads(OLD_CONFIG.read_text())
        del mine["routing"]["high"]
        del mine["surface_reviewers"]["security"]
        (self.p.root / "factory/config.json").write_text(json.dumps(mine))
        res = self.plan("--apply-safe")
        self.assertIn("routing.high", res.stdout)
        self.assertIn("surface_reviewers.security", res.stdout)
        self.assertIn("agents", res.stdout)

    def test_doctor_config_check_passes_after_apply_safe(self):
        self.plan("--apply-safe")
        res = self.p.run("doctor", "--fast")
        self.assertIn("PASS config", res.stdout, res.stdout)

    def test_second_run_changes_nothing_and_config_is_unchanged(self):
        self.plan("--apply-safe")
        before = (self.p.root / "factory/config.json").read_text()
        res = self.plan()
        self.assertIn("unchanged\tfactory/config.json", res.stdout)
        self.plan("--apply-safe")
        self.assertEqual((self.p.root / "factory/config.json").read_text(), before)

    def test_config_not_rewritten_when_nothing_changes(self):
        shutil.copy2(ff.VENDOR / "factory/config.json", self.p.root / "factory/config.json")
        compact = json.dumps(json.loads((ff.VENDOR / "factory/config.json").read_text()))
        (self.p.root / "factory/config.json").write_text(compact)
        self.plan("--apply-safe")
        self.assertEqual((self.p.root / "factory/config.json").read_text(), compact)

    def test_four_space_indent_is_kept(self):
        mine = json.loads(OLD_CONFIG.read_text())
        (self.p.root / "factory/config.json").write_text(json.dumps(mine, indent=4) + "\n")
        self.plan("--apply-safe")
        text = (self.p.root / "factory/config.json").read_text()
        self.assertIn('\n    "concurrency"', text)


class SettledFilesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p = InstalledProject(tmp.name)

    def plan(self, *args):
        res = subprocess.run([sys.executable, str(PLAN), str(self.p.root), *args],
                             capture_output=True, text=True)
        return res, dict(reversed(line.split("\t")) for line in res.stdout.splitlines() if "\t" in line)

    def test_current_config_and_settings_are_unchanged(self):
        res, groups = self.plan()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(groups["factory/config.json"], "unchanged")
        self.assertEqual(groups["factory/runner-settings.json"], "unchanged")

    def test_config_missing_a_key_is_still_config(self):
        path = self.p.root / "factory/config.json"
        cfg = json.loads(path.read_text())
        del cfg["budgets"]
        path.write_text(json.dumps(cfg))
        _, groups = self.plan()
        self.assertEqual(groups["factory/config.json"], "config")

    def test_settings_with_only_project_domains_are_unchanged(self):
        path = self.p.root / "factory/runner-settings.json"
        cfg = json.loads(path.read_text())
        cfg["sandbox"]["network"]["allowedDomains"].append("registry.npmjs.org")
        path.write_text(json.dumps(cfg))
        _, groups = self.plan()
        self.assertEqual(groups["factory/runner-settings.json"], "unchanged")

    def test_settings_missing_an_upstream_domain_is_settings(self):
        path = self.p.root / "factory/runner-settings.json"
        cfg = json.loads(path.read_text())
        cfg["sandbox"]["network"]["allowedDomains"].pop(0)
        path.write_text(json.dumps(cfg))
        _, groups = self.plan()
        self.assertEqual(groups["factory/runner-settings.json"], "settings")


class ResolvedCountTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p = InstalledProject(tmp.name)
        (self.p.root / ff.MANIFEST).unlink()  # an install the manifest doesn't know about
        self.files = ["factory/bin/gate", "factory/bin/route", "factory/bin/doctor", "factory/bin/runner"]
        for rel in self.files:
            (self.p.root / rel).write_text("# old\n")
        self.plan("--apply-safe")  # every differing file is a merge and keeps no manifest entry

    def plan(self, *args):
        return subprocess.run([sys.executable, str(PLAN), str(self.p.root), *args],
                              capture_output=True, text=True)

    def test_files_already_matching_upstream_still_count_until_recorded(self):
        # The user hand-merged: two files now equal upstream, two differ. All four still await
        # --resolved, so the count walks 3, 2, 1, 0 instead of 1, 1, 0, 0.
        for rel in self.files[:2]:
            shutil.copy2(ff.VENDOR / rel, self.p.root / rel)
        left = []
        for rel in self.files:
            res = self.plan("--resolved", rel)
            self.assertEqual(res.returncode, 0, res.stderr)
            left.append(int(res.stdout.rsplit("merges left:", 1)[1]))
        self.assertEqual(left, [3, 2, 1, 0])

    def test_vendor_hash_is_current_only_after_the_last_record(self):
        for rel in self.files[:2]:
            shutil.copy2(ff.VENDOR / rel, self.p.root / rel)
        for rel in self.files[:-1]:
            self.plan("--resolved", rel)
        manifest = json.loads((self.p.root / ff.MANIFEST).read_text())
        self.assertEqual(manifest["vendor_hash"], "pending")
        self.plan("--resolved", self.files[-1])
        manifest = json.loads((self.p.root / ff.MANIFEST).read_text())
        self.assertEqual(manifest["vendor_hash"], ff.vendor_hash())


class PendingCountTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p = InstalledProject(tmp.name)

    def plan(self, *args):
        return subprocess.run([sys.executable, str(PLAN), str(self.p.root), *args],
                              capture_output=True, text=True)

    def manifest(self):
        return json.loads((self.p.root / ff.MANIFEST).read_text())

    def test_stale_settings_core_keeps_the_count_and_vendor_hash_pending(self):
        path = self.p.root / ff.MANIFEST
        m = self.manifest()
        m["settings_core"] = "stale"
        m["vendor_hash"] = "old"
        path.write_text(json.dumps(m))
        shutil.copy2(ff.VENDOR / "factory/bin/job", self.p.root / "factory/bin/job")
        (self.p.root / "factory/bin/gate").write_text("# mine\n")
        m["files"]["factory/bin/gate"] = "0" * 64
        path.write_text(json.dumps(m))
        res = self.plan("--resolved", "factory/bin/gate")
        self.assertEqual(res.returncode, 0, res.stderr)
        left = int(res.stdout.rsplit("merges left:", 1)[1])
        self.assertGreater(left, 0)
        self.assertNotEqual(self.manifest()["vendor_hash"], ff.vendor_hash())

    def test_resolved_with_an_unapplied_safe_row_does_not_mark_current(self):
        m = self.manifest()
        m["vendor_hash"] = "old"
        m["files"]["factory/bin/route"] = "0" * 64  # installed copy equals the recorded old one
        old = "# old route\n"
        (self.p.root / "factory/bin/route").write_text(old)
        m["files"]["factory/bin/route"] = ff.sha256_file(self.p.root / "factory/bin/route")
        m["files"]["factory/bin/gate"] = "0" * 64
        (self.p.root / "factory/bin/gate").write_text("# mine\n")
        (self.p.root / ff.MANIFEST).write_text(json.dumps(m))
        res = self.plan("--resolved", "factory/bin/gate")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotEqual(self.manifest()["vendor_hash"], ff.vendor_hash())


def ff_efforts():
    return json.loads((ff.VENDOR / "factory/config.json").read_text())["effort_levels"]


if __name__ == "__main__":
    unittest.main()
