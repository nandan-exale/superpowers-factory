import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = (ROOT / "skills/factory-install/SKILL.md").read_text()
UPDATE = (ROOT / "skills/factory-update/SKILL.md").read_text()
UNINSTALL = (ROOT / "skills/factory-uninstall/SKILL.md").read_text()
BUILDER = (ROOT / "vendor/factory/factory/agents/builder.md").read_text()
LEARNER = (ROOT / "vendor/factory/factory/agents/learner.md").read_text()
UPSTREAM_INSTALL = (ROOT / "vendor/factory/INSTALL.md").read_text()


class AnyAgentWordingTest(unittest.TestCase):
    def test_skills_find_the_plugin_without_claude_plugin_root(self):
        for text in (INSTALL, UPDATE, UNINSTALL):
            self.assertIn("## Find the plugin", text)
            self.assertIn("git clone --depth 1 --branch", text)
            self.assertNotIn("<skill base>/../../bin", text)
            self.assertNotIn("<skill base>/../../vendor/factory", text)

    def test_install_asks_for_the_runtime_and_its_tiers(self):
        for word in ("claude, codex, opencode, copilot or cursor", "runtimes.<runtime>.tiers",
                     "Stop hook only when the runtime is `claude`", "budgets.job_runs"):
            self.assertIn(word, INSTALL)

    def test_upstream_installer_names_the_runtime_keys(self):
        for word in ("`runtime`", "runtimes.<runtime>.tiers", "budgets.job_runs"):
            self.assertIn(word, UPSTREAM_INSTALL)

    def test_builder_uses_superpowers_when_its_agent_has_them(self):
        self.assertIn("if your agent has them", BUILDER)
        self.assertNotIn("If a skill can't be loaded, write `STATUS: BLOCKED`", BUILDER)

    def test_learner_uses_agents_best_practices_when_available(self):
        self.assertIn("is available, use it", LEARNER)


if __name__ == "__main__":
    unittest.main()
