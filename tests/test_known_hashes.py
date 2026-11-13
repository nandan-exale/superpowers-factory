import hashlib
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

SCRIPT = REPO / "scripts/known-hashes"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def shallow():
    res = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=REPO,
                         capture_output=True, text=True)
    return res.stdout.strip() == "true"


class KnownHashesFileTest(unittest.TestCase):
    def test_every_current_vendored_file_is_listed(self):
        data = json.loads((REPO / "vendor/known-hashes.json").read_text())
        for rel in ff.FILES:
            self.assertIn(ff.sha256_file(ff.VENDOR / rel), data[rel], rel)

    @unittest.skipIf(shallow(), "needs full git history")
    def test_history_gives_job_more_than_one_version(self):
        data = json.loads((REPO / "vendor/known-hashes.json").read_text())
        self.assertGreater(len(data["factory/bin/job"]), 1)

    def test_reader_returns_empty_for_a_missing_file(self):
        env = os.environ.get("FACTORY_KNOWN_HASHES")
        os.environ["FACTORY_KNOWN_HASHES"] = "/nonexistent/known.json"
        try:
            self.assertEqual(ff.known_hashes(), {})
        finally:
            if env is None:
                del os.environ["FACTORY_KNOWN_HASHES"]
            else:
                os.environ["FACTORY_KNOWN_HASHES"] = env

    def test_reader_returns_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "k.json"
            path.write_text('{"factory/bin/gate": ["abc"]}')
            os.environ["FACTORY_KNOWN_HASHES"] = str(path)
            try:
                self.assertEqual(ff.known_hashes(), {"factory/bin/gate": ["abc"]})
            finally:
                del os.environ["FACTORY_KNOWN_HASHES"]


class CheckModeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(REPO / "vendor", self.root / "vendor")

    def check(self):
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "--check"],
                              capture_output=True, text=True)

    def test_check_passes_when_current_versions_are_listed(self):
        res = self.check()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_check_fails_when_a_vendored_file_changed(self):
        path = self.root / "vendor/factory/factory/bin/gate"
        path.write_text(path.read_text() + "# edited\n")
        res = self.check()
        self.assertEqual(res.returncode, 1)
        self.assertIn("factory/bin/gate", res.stdout)

    def test_check_fails_when_the_list_is_missing(self):
        (self.root / "vendor/known-hashes.json").unlink()
        self.assertEqual(self.check().returncode, 1)
