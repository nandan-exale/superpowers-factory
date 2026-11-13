import json
import tempfile
import unittest
from pathlib import Path

from script_loader import load_script

PLUGIN = Path(__file__).resolve().parents[1]


class ShippedEvalsTest(unittest.TestCase):
    def setUp(self):
        self.ev = load_script(PLUGIN / "scripts" / "eval", "eval_shipped")
        self.cfg = json.loads(self.ev.CONFIG.read_text())

    def test_every_case_is_valid_and_its_agent_resolves(self):
        cases = self.ev.load_cases(self.ev.EVALS)
        self.assertEqual(sorted(f"{a}/{c}" for a, c, _ in cases), [
            "approver/disagreeing-reviews", "intake/accept", "intake/needs-info", "intake/reject",
            "learner/none", "reviewer-code/clean", "reviewer-code/deleted-test", "reviewer-code/off-by-one",
            "reviewer-security/hardcoded-key"])
        for agent, _, _ in cases:
            self.ev.agent_prompt(agent)
            self.ev.model_for(agent, self.cfg)

    def test_every_workspace_builds(self):
        for _, _, case_dir in self.ev.load_cases(self.ev.EVALS):
            with tempfile.TemporaryDirectory() as tmp:
                self.ev.workspace(case_dir, Path(tmp))
                self.assertTrue((Path(tmp) / "pager.py").is_file(), case_dir)

    def test_baseline_is_a_map_of_rates(self):
        baseline = json.loads(self.ev.BASELINE.read_text())
        self.assertTrue(all(0 <= v <= 1 for v in baseline.values()))
