import unittest
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor/factory"
BUILDER = (VENDOR / "factory/agents/builder.md").read_text()
SKILL = (VENDOR / ".claude/skills/factory/SKILL.md").read_text()


class WordingTest(unittest.TestCase):
    def test_skill_no_longer_names_the_builder(self):
        self.assertNotIn("builder-<id>", SKILL)
        self.assertIn("resume it with `SendMessage` to the agent id", SKILL)

    def test_skill_says_where_base_comes_from(self):
        self.assertIn("built from `job.json` and `base_branch` in `factory/config.json`", SKILL)

    def test_builder_never_edits_the_planned_spec_or_plan(self):
        self.assertIn("Never edit the spec or plan files the job was planned from", BUILDER)

    def test_builder_skips_tags_and_lists_skipped_steps_for_the_human(self):
        self.assertIn("worktree or tag", BUILDER)
        self.assertIn("`For the human: <step>`", BUILDER)


if __name__ == "__main__":
    unittest.main()
