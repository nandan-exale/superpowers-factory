import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "vendor/factory/.claude/skills/factory/SKILL.md"


class SkillWordingTest(unittest.TestCase):
    def test_report_command_and_end_of_run_steps(self):
        text = SKILL.read_text()
        self.assertIn("/factory report", text)
        self.assertIn("factory/bin/job report --write", text)
        self.assertIn("factory/bin/job digest", text)
