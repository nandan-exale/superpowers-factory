import unittest
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[1] / "plugin/skills/factory-handoff/SKILL.md").read_text()


class HandoffSkillTest(unittest.TestCase):
    def test_runs_the_check_script(self):
        for needle in ("factory-handoff-check", "on-origin-base", "risky:", "the factory will skip them"):
            self.assertIn(needle, SKILL)

    def test_no_longer_lists_the_individual_checks(self):
        for needle in ("gh label list", "--limit 200", "git cat-file", "git merge-base",
                       "git status --porcelain", "gh auth status"):
            self.assertNotIn(needle, SKILL)

    def test_warns_when_the_approver_will_escalate(self):
        self.assertIn("factory/agents/approver.md", SKILL)
        self.assertIn("will stop at needs-human for you to merge", SKILL)

    def test_splits_large_plans_into_parts(self):
        text = (Path(__file__).resolve().parents[1] / "plugin/skills/factory-handoff/SKILL.md").read_text()
        for needle in ("handoff.max_tasks_per_part", "part: <k>/<n>", "tasks: <first>-<last>",
                       "depends: #<previous part's issue>", "(part <k>/<n>)", "one issue per part, in order"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
