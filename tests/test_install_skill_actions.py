import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills/factory-install/SKILL.md"


class InstallActionsTest(unittest.TestCase):
    def test_offers_the_workflow_off_by_default_with_secrets_and_a_public_repo_warning(self):
        text = SKILL.read_text()
        for needle in ("factory/bin/runner workflow --claude-version", ".github/workflows/factory-runner.yml",
                       "FACTORY_CLAUDE_TOKEN", "FACTORY_GH_TOKEN", "gh repo view --json visibility",
                       "never ask for", "off by default", "factory/bin/doctor --ci"):
            self.assertIn(needle, text)
