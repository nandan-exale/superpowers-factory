import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from factory_project import FactoryProject
from script_loader import load_script

PLUGIN = Path(__file__).resolve().parents[1]


class ShippedScenariosTest(unittest.TestCase):
    def test_every_shipped_scenario_is_valid(self):
        e2e = load_script(PLUGIN / "scripts" / "e2e", "e2e_shipped")
        names = [n for n, _ in e2e.load_scenarios(PLUGIN / "tests" / "e2e")]
        self.assertEqual(names, ["budget-stop", "happy-path", "learning", "needs-info",
                                 "runner-tick", "tagged-finding"])


class LearningSeedTest(unittest.TestCase):
    def test_seeded_jobs_make_job_learn_fire_and_old_learning_state_is_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = FactoryProject(tmp)
            stale = project.repo / "factory" / "jobs" / "learning" / "state.json"
            stale.parent.mkdir(parents=True)
            stale.write_text(json.dumps({"convention": {"filed": "2099-01-01T00:00:00Z"}}))
            setup = PLUGIN / "tests" / "e2e" / "learning" / "setup.py"
            subprocess.run([sys.executable, str(setup), str(project.repo)], check=True)
            self.assertFalse(stale.exists())
            res = subprocess.run([sys.executable, "factory/bin/job", "learn"], cwd=project.repo,
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("LEARN: convention (3 jobs)", res.stdout)
