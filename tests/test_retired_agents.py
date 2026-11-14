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

import factory_files as ff  # noqa: E402


def sha(data):
    return hashlib.sha256(data).hexdigest()


class RetiredAgentsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name)
        self.known = self.project / "known.json"
        old = b"---\nname: approver\n---\nold\n"
        self.known.write_text(json.dumps({".claude/agents/approver.md": [sha(old)]}))
        (self.project / ".claude/agents").mkdir(parents=True)
        (self.project / ".claude/agents/approver.md").write_bytes(old)
        (self.project / ".claude/agents/builder.md").write_text("my own edits\n")
        (self.project / "factory/bin").mkdir(parents=True)
        (self.project / "factory/bin/job").write_text("# an installed factory\n")

    def plan(self, *extra):
        env = {**os.environ, "FACTORY_KNOWN_HASHES": str(self.known)}
        return subprocess.run([sys.executable, str(REPO / "bin/factory-update-plan"), str(self.project), *extra],
                              capture_output=True, text=True, env=env)

    def test_retired_lists_every_old_agent_path(self):
        self.assertEqual(set(ff.RETIRED), {f".claude/agents/{n}.md" for n in ff.AGENTS})

    def test_unedited_old_copy_is_retired_and_edited_one_is_flagged(self):
        out = self.plan().stdout
        self.assertRegex(out, r"retired\s+\.claude/agents/approver\.md")
        self.assertRegex(out, r"retired-edited\s+\.claude/agents/builder\.md")

    def test_apply_safe_deletes_only_unedited_retired_files(self):
        res = self.plan("--apply-safe")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((self.project / ".claude/agents/approver.md").exists())
        self.assertTrue((self.project / ".claude/agents/builder.md").exists())


if __name__ == "__main__":
    unittest.main()
