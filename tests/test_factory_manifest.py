import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import factory_files as ff  # noqa: E402


class ManifestTest(unittest.TestCase):
    def test_every_listed_file_exists_in_vendor(self):
        for rel in ff.FILES:
            self.assertTrue((ff.VENDOR / rel).is_file(), rel)

    def test_install_skill_copies_every_listed_file(self):
        text = (REPO / "skills/factory-install/SKILL.md").read_text()
        for rel in ff.FILES:
            self.assertIn(rel, text)

    def test_vendor_hash_is_deterministic_and_content_sensitive(self):
        self.assertEqual(ff.vendor_hash(), ff.vendor_hash())
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "factory"
            shutil.copytree(ff.VENDOR, copy)
            self.assertEqual(ff.vendor_hash(copy), ff.vendor_hash())
            (copy / "factory/bin/job").write_text("changed\n")
            self.assertNotEqual(ff.vendor_hash(copy), ff.vendor_hash())

    def test_manifest_records_vendored_hashes(self):
        data = ff.manifest_data()
        self.assertEqual(data["vendor_hash"], ff.vendor_hash())
        self.assertEqual(set(data["files"]), set(ff.FILES))
        for rel in ff.FILES:
            want = hashlib.sha256((ff.VENDOR / rel).read_bytes()).hexdigest()
            self.assertEqual(data["files"][rel], want)

    def test_script_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "factory").mkdir()
            res = subprocess.run([sys.executable, str(REPO / "bin/factory-manifest"), tmp],
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            written = json.loads((Path(tmp) / "factory/manifest.json").read_text())
            self.assertEqual(written, ff.manifest_data())

    def test_script_refuses_without_factory_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = subprocess.run([sys.executable, str(REPO / "bin/factory-manifest"), tmp],
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertIn("has no factory/ directory", res.stderr)


if __name__ == "__main__":
    unittest.main()
