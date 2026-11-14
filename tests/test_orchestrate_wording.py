import unittest
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[1] / "vendor/factory/.claude/skills/factory/SKILL.md").read_text()


class SkillWordingTest(unittest.TestCase):
    def test_run_goes_through_the_script(self):
        self.assertIn("factory/bin/orchestrate run", SKILL)

    def test_no_claude_code_spawning_left(self):
        for word in ("subagent_type", "SendMessage", "Agent tool", "WAIT FOR ALL"):
            self.assertNotIn(word, SKILL, word)

    def test_talking_to_the_factory_is_kept(self):
        for text in ("factory/bin/job feedback", "factory/bin/job reject", "factory/bin/job resume",
                     "gh issue create --label factory", "factory/bin/job report"):
            self.assertIn(text, SKILL, text)


if __name__ == "__main__":
    unittest.main()
