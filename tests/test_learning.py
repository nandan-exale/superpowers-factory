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


class LearnTest(LearningCase):
    def learn(self):
        return self.run_main("learn").strip().splitlines()

    def three_jobs_with(self, finding, lens="code"):
        ids = [self.job_id, self.new_job(8), self.new_job(9)]
        for job_id in ids:
            self.review(job_id, lens, [finding])
        return ids

    def test_nothing_recurring(self):
        self.review(self.job_id, "code", ["[missing-test] a.py:1 x"])
        self.assertEqual(self.learn(), ["LEARN: none"])

    def test_tag_in_three_jobs_is_learned(self):
        self.three_jobs_with("[missing-test] a.py:1 add a test")
        [line] = self.learn()
        self.assertTrue(line.startswith("LEARN: missing-test (3 jobs) factory/jobs/learning/missing-test/evidence.md"))
        evidence = (self.job.LEARNING / "missing-test" / "evidence.md").read_text()
        self.assertIn("> a.py:1 add a test", evidence)
        self.assertIn("quoted data", evidence)

    def test_counts_distinct_jobs_not_findings(self):
        self.review(self.job_id, "code", ["[convention] a", "[convention] b", "[convention] c"])
        self.review(self.job_id, "ui", ["[convention] d"])
        self.assertEqual(self.learn(), ["LEARN: none"])

    def test_old_reviews_are_outside_the_window(self):
        ids = [self.job_id, self.new_job(8), self.new_job(9)]
        for job_id in ids[:2]:
            self.review(job_id, "code", ["[dead-code] x"])
        self.review(ids[2], "code", ["[dead-code] x"], age_days=45)
        self.assertEqual(self.learn(), ["LEARN: none"])

    def test_other_slug_tags_count_per_slug(self):
        self.three_jobs_with("[other:n-plus-one] loop queries")
        [line] = self.learn()
        self.assertIn("LEARN: other:n-plus-one (3 jobs) factory/jobs/learning/other--n-plus-one/evidence.md", line)

    def test_recently_filed_tags_are_skipped(self):
        self.three_jobs_with("[missing-test] x")
        self.job.LEARNING.mkdir(parents=True, exist_ok=True)
        (self.job.LEARNING / "state.json").write_text(json.dumps(
            {"missing-test": {"issue": 5, "filed": self.job.now()}}))
        self.assertEqual(self.learn(), ["LEARN: none"])

    def test_evidence_includes_escalation_reasons(self):
        ids = self.three_jobs_with("[spec-gap] x")
        (self.job.job_dir(ids[1]) / "decision.md").write_text("ESCALATE\n\n## Why\nThe spec was vague.\n")
        self.learn()
        evidence = (self.job.LEARNING / "spec-gap" / "evidence.md").read_text()
        self.assertIn("> The spec was vague.", evidence)


if __name__ == "__main__":
    unittest.main()
