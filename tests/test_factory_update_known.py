import hashlib
import json
import os
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
GATE = "factory/bin/gate"
OLD = "# an old upstream gate\n"


class KnownHashTest(unittest.TestCase):
    """A project without a manifest entry for a file: old upstream copy vs. the project's own edit."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.p = InstalledProject(tmp.name)  # creates <tmp>/project
        (self.p.root / ff.MANIFEST).unlink()
        known = self.tmp / "known.json"
        known.write_text(json.dumps({GATE: [hashlib.sha256(OLD.encode()).hexdigest()]}))
        self.env = {**os.environ, "FACTORY_KNOWN_HASHES": str(known)}

    def plan(self, *args):
        res = subprocess.run([sys.executable, str(PLAN), str(self.p.root), *args],
                             capture_output=True, text=True, env=self.env)
        return res, dict(reversed(line.split("\t")) for line in res.stdout.splitlines() if "\t" in line)

    def test_unedited_old_copy_is_safe(self):
        (self.p.root / GATE).write_text(OLD)
        res, groups = self.plan()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(groups[GATE], "safe")

    def test_edited_copy_is_still_merge(self):
        (self.p.root / GATE).write_text("# my own gate\n")
        _, groups = self.plan()
        self.assertEqual(groups[GATE], "merge")

    def test_missing_list_keeps_merge(self):
        (self.p.root / GATE).write_text(OLD)
        self.env["FACTORY_KNOWN_HASHES"] = str(self.tmp / "nope.json")
        _, groups = self.plan()
        self.assertEqual(groups[GATE], "merge")

    def test_apply_safe_replaces_the_old_copy_and_records_it(self):
        (self.p.root / GATE).write_text(OLD)
        res, _ = self.plan("--apply-safe")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.p.root / GATE).read_bytes(), (ff.VENDOR / GATE).read_bytes())
        manifest = json.loads((self.p.root / ff.MANIFEST).read_text())
        self.assertEqual(manifest["files"][GATE], ff.sha256_file(ff.VENDOR / GATE))


if __name__ == "__main__":
    unittest.main()
