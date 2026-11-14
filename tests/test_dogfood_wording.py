import unittest
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor/factory"
BUILDER = (VENDOR / "factory/agents/builder.md").read_text()
SKILL = (VENDOR / ".claude/skills/factory/SKILL.md").read_text()


class WordingTest(unittest.TestCase):
    def test_skill_no_longer_names_the_builder(self):
        # Resuming the builder by its session and the header's base branch are orchestrate's now:
        # tests.test_pipeline checks them.
        self.assertNotIn("builder-<id>", SKILL)

    def test_builder_never_edits_the_planned_spec_or_plan(self):
        self.assertIn("Never edit the spec or plan files the job was planned from", BUILDER)

    def test_builder_skips_tags_and_lists_skipped_steps_for_the_human(self):
        self.assertIn("worktree or tag", BUILDER)
        self.assertIn("`For the human: <step>`", BUILDER)


if __name__ == "__main__":
    unittest.main()
