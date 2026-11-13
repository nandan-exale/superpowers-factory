import unittest
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor/factory"


class SafetyWordingTest(unittest.TestCase):
    def test_skill_watches_first_and_respects_the_pause(self):
        text = (VENDOR / ".claude/skills/factory/SKILL.md").read_text()
        self.assertIn("factory/bin/job watch", text)
        self.assertIn("PAUSED:", text)
        self.assertIn("factory/bin/job resume", text)
        self.assertIn("factory:risk-ok added", text)

    def test_runner_watches_in_its_chores(self):
        text = (VENDOR / "factory/bin/runner").read_text()
        self.assertIn('["watch"]', text)

    def test_dashboard_shows_the_pause(self):
        self.assertIn("jobs/paused.json", (VENDOR / "factory/dashboard.html").read_text())

    def test_install_and_uninstall_handle_the_labels(self):
        root = Path(__file__).resolve().parents[1] / "skills"
        install = (root / "factory-install/SKILL.md").read_text()
        uninstall = (root / "factory-uninstall/SKILL.md").read_text()
        for name in ("factory:revert", "factory:risk-ok"):
            self.assertIn(f"gh label create {name}", install)
            self.assertIn(f"gh label delete {name} --yes", uninstall)
