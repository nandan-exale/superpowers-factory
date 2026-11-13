import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import FactoryProject  # noqa: E402


class CostByModelTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        self.needle = "Job folder: /x/factory/jobs/001-a/"

    def transcript(self, name, model, input_tokens):
        sub = self.job.transcripts_dir() / "s1" / "subagents"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"agent-{name}.jsonl").write_text(
            json.dumps({"message": {"content": f"{self.needle} go"}}) + "\n"
            + json.dumps({"type": "assistant", "message": {
                "id": f"m-{name}", "model": model, "usage": {"input_tokens": input_tokens, "output_tokens": 0}}})
            + "\n")

    def test_split_by_model_and_total_matches(self):
        self.transcript("a", "claude-opus-5-5", 1_000_000)     # $4.00
        self.transcript("b", "claude-sonnet-5-5", 500_000)     # $1.00
        self.transcript("c", "claude-opus-5-5", 250_000)       # $1.00
        by = self.job.cost_by_model(self.needle)
        self.assertEqual(by, {"claude-opus-5-5": 5.0, "claude-sonnet-5-5": 1.0})
        self.assertEqual(self.job.cost_for_needle(self.needle), 6.0)

    def test_other_jobs_do_not_count(self):
        self.transcript("a", "claude-opus-5-5", 1_000_000)
        self.assertEqual(self.job.cost_by_model("Job folder: /x/factory/jobs/002-b/"), {})

    def test_model_summary_is_largest_first_without_prefix(self):
        self.assertEqual(self.job.model_summary({"claude-sonnet-5-5": 0.6, "claude-opus-5-5": 4.97}),
                         "opus-5-5 $4.97, sonnet-5-5 $0.60")
        self.assertEqual(self.job.model_summary({}), "none")

    def test_job_costs_prints_each_model_and_the_total(self):
        self.project.set_issue("Build it.", labels=("factory",))
        job_id = self.project.create_job(self.job)
        needle = f"Job folder: {self.job.job_dir(job_id)}/"
        self.needle = needle
        self.transcript("a", "claude-opus-5-5", 1_000_000)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.main(["costs", job_id])
        self.assertEqual(out.getvalue().splitlines(), ["claude-opus-5-5  $4.00", "total $4.00"])


if __name__ == "__main__":
    unittest.main()
