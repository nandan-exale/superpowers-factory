import unittest
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[1] / "skills/factory-handoff/SKILL.md").read_text()


class HandoffSkillTest(unittest.TestCase):
    def test_checks_for_steps_outside_the_job_branch(self):
        for needle in ("git tag", "--force", "git checkout", "git merge"):
            self.assertIn(needle, SKILL)
        self.assertIn("the factory will skip them", SKILL)

    def test_warns_when_the_approver_will_escalate(self):
        self.assertIn(".claude/agents/approver.md", SKILL)
        self.assertIn("will stop at needs-human for you to merge", SKILL)


if __name__ == "__main__":
    unittest.main()
