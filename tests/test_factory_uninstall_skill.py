import re
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SKILL = PLUGIN / "skills/factory-uninstall/SKILL.md"


def step(n):
    text = SKILL.read_text()
    return text[text.index(f"\n{n}. "):text.index(f"\n{n + 1}. ")]


class FilesStepTest(unittest.TestCase):
    def test_only_manifest_keys_in_files_are_deleted(self):
        files = step(4)
        self.assertIn("`FILES`", files)
        self.assertIn("only", files)
        for refused in ("absolute", "`..`", "isn't in `FILES`", "never delete"):
            self.assertIn(refused, " ".join(files.split()))

    def test_empty_directory_cleanup_keeps_job_history(self):
        command = re.search(r"`(find factory \.claude [^`]*)`", step(4)).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ("factory/jobs/001/round-2", "factory/bin", ".claude/agents", ".claude/skills/factory"):
                (root / rel).mkdir(parents=True)
            subprocess.run(command, shell=True, cwd=root, check=True)
            self.assertTrue((root / "factory/jobs/001/round-2").is_dir())
            for gone in ("factory/bin", ".claude"):
                self.assertFalse((root / gone).exists(), gone)

    def test_empty_job_history_folder_is_kept(self):
        command = re.search(r"`(find factory \.claude [^`]*)`", step(4)).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ("factory/jobs", ".claude"):
                (root / rel).mkdir(parents=True)
            subprocess.run(command, shell=True, cwd=root, check=True)
            self.assertTrue((root / "factory/jobs").is_dir())


class DigestLabelTest(unittest.TestCase):
    def test_deletes_the_digest_label(self):
        text = (PLUGIN / "skills" / "factory-uninstall" / "SKILL.md").read_text()
        self.assertIn("gh label delete factory:digest --yes", text)

    def test_install_creates_the_digest_label(self):
        text = (PLUGIN / "skills" / "factory-install" / "SKILL.md").read_text()
        self.assertIn("gh label create factory:digest", text)


if __name__ == "__main__":
    unittest.main()
