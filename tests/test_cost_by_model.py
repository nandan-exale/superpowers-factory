import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import FactoryProject  # noqa: E402


class CostByModelTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        self.folder = Path(tmp.name) / "factory" / "jobs" / "001-a"

    def run_file(self, name, model, usd, folder=None):
        d = (folder or self.folder) / "runs"
        d.mkdir(parents=True, exist_ok=True)
        seq = len(list(d.glob("*.json"))) + 1
        (d / f"{seq:03d}-{name}.json").write_text(json.dumps({"cost_usd": usd, "cost_by_model": {model: usd}}))

    def test_split_by_model_and_total_matches(self):
        self.run_file("a", "claude-opus-5-5", 4.0)
        self.run_file("b", "claude-sonnet-5-5", 1.0)
        self.run_file("c", "claude-opus-5-5", 1.0)
        by = self.job.cost_by_model(self.folder)
        self.assertEqual(by, {"claude-opus-5-5": 5.0, "claude-sonnet-5-5": 1.0})
        self.assertEqual(self.job.cost_for_folder(self.folder), 6.0)

    def test_other_jobs_do_not_count(self):
        self.run_file("a", "claude-opus-5-5", 4.0)
        other = self.folder.parent / "002-b"
        other.mkdir(parents=True)
        self.assertEqual(self.job.cost_by_model(other), {})

    def test_model_summary_is_largest_first_without_prefix(self):
        self.assertEqual(self.job.model_summary({"claude-sonnet-5-5": 0.6, "claude-opus-5-5": 4.97}),
                         "opus-5-5 $4.97, sonnet-5-5 $0.60")
        self.assertEqual(self.job.model_summary({}), "none")

    def test_job_costs_prints_each_model_and_the_total(self):
        self.project.set_issue("Build it.", labels=("factory",))
        job_id = self.project.create_job(self.job)
        self.run_file("a", "claude-opus-5-5", 4.0, folder=self.job.job_dir(job_id))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.main(["costs", job_id])
        self.assertEqual(out.getvalue().splitlines(), ["claude-opus-5-5  $4.00", "total $4.00"])


if __name__ == "__main__":
    unittest.main()
