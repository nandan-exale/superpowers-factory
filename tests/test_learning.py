import json
import os
import time
import unittest

from budget_case import AGENTS, BudgetCase


class LearningCase(BudgetCase):
    def setUp(self):
        super().setUp()
        self.job.CONFIG["concurrency"] = 20
        self.job.CONCURRENCY = 20  # read once at import; job create checks it

    def review(self, job_id, lens, findings, round_n=1, verdict="CHANGES", age_days=0):
        rd = self.job.job_dir(job_id) / f"round-{round_n}"
        rd.mkdir(parents=True, exist_ok=True)
        items = "\n".join(f"{i}. {f}" for i, f in enumerate(findings, 1)) or "None."
        path = rd / f"review-{lens}.md"
        path.write_text(f"VERDICT: {verdict}\n\n## Summary\n- x\n\n## Findings\n{items}\n")
        if age_days:
            t = time.time() - age_days * 86400
            os.utime(path, (t, t))
        return path

    def new_job(self, number):
        self.project.set_issue("Build it.", labels=("factory",), number=number)
        return self.project.create_job(self.job)


class TaggedFindingsTest(LearningCase):
    def in_review_with(self, findings):
        self.in_review()
        self.review(self.job_id, "code", findings)
        return self.current()["reviews"]["code"]

    def test_tagged_findings_are_valid(self):
        self.assertEqual(self.in_review_with(["[missing-test] a.py:3 add a test"]), "CHANGES")

    def test_other_slug_is_valid(self):
        self.assertEqual(self.in_review_with(["[other:n-plus-one] a.py:9 batch it"]), "CHANGES")

    def test_none_is_valid(self):
        self.assertEqual(self.in_review_with([]), "CHANGES")

    def test_untagged_finding_is_invalid(self):
        self.assertEqual(self.in_review_with(["a.py:3 add a test"]), "invalid")

    def test_unknown_tag_is_invalid(self):
        self.assertEqual(self.in_review_with(["[made-up] a.py:3 x"]), "invalid")

    def test_bad_learning_config_dies(self):
        self.job.CONFIG["learning"]["threshold"] = 0
        with self.assertRaises(SystemExit):
            self.job.learning_config()


if __name__ == "__main__":
    unittest.main()
