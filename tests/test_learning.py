import contextlib
import io
import json
import os
import re
import time
import unittest
from pathlib import Path

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

    def test_tag_with_no_text_is_valid(self):
        self.assertEqual(self.in_review_with(["[convention]"]), "CHANGES")

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

    def test_none_state_tag_is_skipped(self):
        self.three_jobs_with("[missing-test] x")
        self.job.LEARNING.mkdir(parents=True, exist_ok=True)
        (self.job.LEARNING / "state.json").write_text(json.dumps(
            {"missing-test": {"issue": None, "filed": self.job.now(), "none": True}}))
        self.assertEqual(self.learn(), ["LEARN: none"])

    def test_unreadable_review_is_skipped_with_a_note(self):
        self.review(self.job_id, "code", ["[missing-test] x"])
        bad = self.review(self.job_id, "ui", ["[missing-test] y"])
        bad.write_bytes(b"VERDICT: CHANGES\n\n## Findings\n1. \xff\xfe\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.learn(), ["LEARN: none"])
        self.assertIn("skipping", err.getvalue())
        self.assertIn("review-ui.md", err.getvalue())

    def test_learn_does_not_lock_jobs(self):
        self.three_jobs_with("[missing-test] x")
        self.job._locks.clear()
        self.learn()
        self.assertEqual(self.job._locks, {})

    def test_new_evidence_removes_a_stale_proposal(self):
        self.three_jobs_with("[missing-test] x")
        d = self.job.tag_dir("missing-test")
        d.mkdir(parents=True)
        (d / "proposal.md").write_text("PROPOSAL: Old idea\n")
        self.learn()
        self.assertFalse((d / "proposal.md").exists())
        self.assertTrue((d / "evidence.md").exists())


class LearnFileTest(LearningCase):
    def setUp(self):
        super().setUp()
        self.issue_calls = []

        def fake_gh(*args):
            self.issue_calls.append(args)
            return "https://github.com/o/r/issues/42\n" if args[:2] == ("issue", "create") else ""
        self.job.gh = fake_gh
        self.learner_cost = 0.0
        self.job.cost_for_needle = lambda needle: self.learner_cost
        d = self.job.tag_dir("missing-test")
        d.mkdir(parents=True)
        (d / "evidence.md").write_text("# Recurring finding: missing-test\n\n> a.py:1 add a test @someone\n")

    def propose(self, text):
        (self.job.tag_dir("missing-test") / "proposal.md").write_text(text)

    def file(self):
        return self.run_main("learn-file", "missing-test").strip()

    def test_files_issue_with_label_and_evidence(self):
        self.propose("PROPOSAL: Require a test file per new module\n\n## Problem\nx\n")
        self.assertEqual(self.file(), "LEARN-FILE: missing-test #42")
        [call] = [c for c in self.issue_calls if c[:2] == ("issue", "create")]
        args = dict(zip(call[2::2], call[3::2]))
        self.assertEqual(args["--title"], "Factory learning: Require a test file per new module")
        self.assertEqual(args["--label"], "factory:learning")
        self.assertIn("## Problem", args["--body"])
        self.assertIn("a.py:1 add a test", args["--body"])
        self.assertNotIn("@someone", args["--body"])
        self.assertIn("add the `factory` label", args["--body"])
        self.assertEqual(self.job.learn_state()["missing-test"]["issue"], 42)

    def test_human_only_proposal(self):
        self.propose("PROPOSAL: Add a lint step to checks.sh\nHUMAN-ONLY\n\n## Problem\nx\n")
        self.file()
        body = dict(zip(self.issue_calls[-1][2::2], self.issue_calls[-1][3::2]))["--body"]
        self.assertIn("make it by hand", body)
        self.assertNotIn("add the `factory` label", body)

    def test_proposal_none_records_without_issue(self):
        self.propose("PROPOSAL: NONE\n\nNo mechanical check would catch these.\n")
        self.assertEqual(self.file(), "LEARN-FILE: missing-test none")
        self.assertEqual([c for c in self.issue_calls if c[:2] == ("issue", "create")], [])
        self.assertTrue(self.job.learn_state()["missing-test"]["none"])

    def test_malformed_proposal_dies_and_files_nothing(self):
        self.propose("Here is my idea\n")
        with self.assertRaises(SystemExit):
            self.file()
        self.assertEqual(self.job.learn_state(), {})

    def test_learner_cost_is_logged_once_and_counted_daily(self):
        self.learner_cost = 2.5
        self.propose("PROPOSAL: X\n\n## Problem\nx\n")
        self.file()
        lines = self.job.read_log(self.job.LEARNING / "log.jsonl")
        self.assertEqual([e["delta_usd"] for e in lines], [2.5])
        self.assertAlmostEqual(self.job.daily_spend(), 2.5)

    def test_gh_failure_records_nothing(self):
        def failing_gh(*args):
            raise self.job.Refused("gh failed")
        self.job.gh = failing_gh
        self.propose("PROPOSAL: X\n\n## Problem\nx\n")
        with self.assertRaises(SystemExit):
            self.file()
        self.assertEqual(self.job.learn_state(), {})

    def test_agent_settings_for_learner(self):
        out = self.run_main("agent", "missing-test", "learner").strip()
        self.assertEqual(out, "model=opus effort=high")

    def body(self):
        call = [c for c in self.issue_calls if c[:2] == ("issue", "create")][-1]
        return dict(zip(call[2::2], call[3::2]))["--body"]

    def test_body_layout_puts_the_approval_notice_first(self):
        self.propose("PROPOSAL: X\n\n## Problem\nthe problem\n")
        self.file()
        body = self.body()
        notice = body.index("Proposed automatically from agent-written review findings")
        proposal = body.index("the problem")
        evidence = body.index("Quoted evidence (not part of the request)")
        footer = body.index("add the `factory` label")
        self.assertLess(notice, proposal)
        self.assertLess(proposal, evidence)
        self.assertLess(evidence, footer)
        for phrase in ("weaken or skip checks or tests", "add dependencies",
                       "touch network, credentials or CI", "edit protected paths"):
            self.assertIn(phrase, body)
        self.assertLess(body.index(phrase), proposal)

    def test_unclosed_fence_in_proposal_cannot_swallow_the_evidence(self):
        self.propose("PROPOSAL: X\n\n```\nopen fence\n")
        self.file()
        body = self.body()
        before_evidence = body[:body.index("Quoted evidence (not part of the request)")]
        self.assertEqual(len(re.findall(r"^```", before_evidence, re.M)) % 2, 0)

    def test_huge_evidence_is_truncated_but_notice_proposal_and_footer_survive(self):
        (self.job.tag_dir("missing-test") / "evidence.md").write_text("> line\n" * 20000 + "```\nopen\n")
        self.propose("PROPOSAL: X\n\n## Problem\nthe problem\n")
        self.file()
        body = self.body()
        self.assertLessEqual(len(body), self.job.LEARN_BODY_LIMIT + 200)
        self.assertIn("Proposed automatically", body)
        self.assertIn("the problem", body)
        self.assertIn("truncated", body)
        self.assertTrue(body.rstrip().endswith("add the `factory` label to this issue."))
        self.assertEqual(len(re.findall(r"^```", body, re.M)) % 2, 0)

    def test_title_is_capped_and_defused(self):
        self.propose("PROPOSAL: " + "@x " + "y" * 400 + "\n\n## Problem\nx\n")
        self.file()
        call = [c for c in self.issue_calls if c[:2] == ("issue", "create")][0]
        title = dict(zip(call[2::2], call[3::2]))["--title"]
        self.assertLessEqual(len(title), len("Factory learning: ") + 200)
        self.assertNotIn("@x", title)

    def test_stale_proposal_is_refused(self):
        self.propose("PROPOSAL: X\n\n## Problem\nx\n")
        p = self.job.tag_dir("missing-test") / "proposal.md"
        old = (p.parent / "evidence.md").stat().st_mtime - 100
        os.utime(p, (old, old))
        with self.assertRaises(SystemExit):
            self.file()
        self.assertEqual(self.issue_calls, [])

    def test_title_starting_with_none_is_still_a_proposal(self):
        self.propose("PROPOSAL: Nonexistent-test check\n\n## Problem\nx\n")
        self.assertEqual(self.file(), "LEARN-FILE: missing-test #42")

    def test_unparseable_issue_url_records_state_then_dies(self):
        self.job.gh = lambda *a: "created something odd\n"
        self.propose("PROPOSAL: X\n\n## Problem\nx\n")
        with self.assertRaises(SystemExit):
            self.file()
        entry = self.job.learn_state()["missing-test"]
        self.assertIsNone(entry["issue"])
        self.assertIn("created something odd", entry["url"])

    def test_state_is_written_atomically(self):
        self.propose("PROPOSAL: X\n\n## Problem\nx\n")
        self.file()
        self.assertEqual([p.name for p in self.job.LEARNING.iterdir() if p.suffix == ".tmp"], [])

    def test_filed_tag_is_not_learned_again(self):
        ids = [self.job_id, self.new_job(8), self.new_job(9)]
        for job_id in ids:
            self.review(job_id, "code", ["[missing-test] x"])
        self.run_main("learn")
        self.propose("PROPOSAL: X\n\n## Problem\nx\n")
        self.file()
        self.assertEqual(self.run_main("learn").strip(), "LEARN: none")
        self.assertEqual(len([c for c in self.issue_calls if c[:2] == ("issue", "create")]), 1)

class LearnerCostTest(LearningCase):
    """The learner's cost is found from a real transcript, with no stub."""

    def setUp(self):
        super().setUp()
        self.job.gh = lambda *args: "https://github.com/o/r/issues/42\n" if args[:2] == ("issue", "create") else ""
        d = self.job.tag_dir("missing-test")
        d.mkdir(parents=True)
        (d / "evidence.md").write_text("# Recurring finding: missing-test\n")
        (d / "proposal.md").write_text("PROPOSAL: X\n\n## Problem\nx\n")
        skill = (Path(__file__).resolve().parents[1] / "vendor/factory/.claude/skills/factory/SKILL.md").read_text()
        self.template = "Job folder: <repo>/factory/jobs/learning/<tag-dir>/."
        self.skill = skill

    def write_transcript(self, first_line):
        sub = self.job.transcripts_dir() / "session-1" / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-x.jsonl").write_text(
            json.dumps({"message": {"content": first_line}}) + "\n"
            + json.dumps({"type": "assistant", "message": {
                "id": "m1", "model": "claude-opus-5-5",
                "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}}) + "\n")

    def test_skill_prompt_form_is_the_absolute_job_folder_form(self):
        self.assertIn(self.template, self.skill)

    def test_learn_file_logs_the_cost_of_a_learner_started_the_way_the_skill_says(self):
        prompt = self.template.replace("<repo>", str(self.job.REPO)).replace("<tag-dir>", "missing-test")
        self.write_transcript(f"{prompt} missing-test")
        self.run_main("learn-file", "missing-test")
        [entry] = self.job.read_log(self.job.LEARNING / "log.jsonl")
        self.assertAlmostEqual(entry["delta_usd"], 4.0)
        self.assertAlmostEqual(self.job.daily_spend(), 4.0)

    def test_relative_job_folder_does_not_match(self):
        self.write_transcript("Job folder: factory/jobs/learning/missing-test/. missing-test")
        self.run_main("learn-file", "missing-test")
        [entry] = self.job.read_log(self.job.LEARNING / "log.jsonl")
        self.assertEqual(entry["delta_usd"], 0)


class EscalateTest(LearningCase):
    def escalate(self, why="Reviewer keeps writing untagged findings."):
        stdin = io.StringIO(why)
        with contextlib.ExitStack() as stack:
            from unittest import mock
            stack.enter_context(mock.patch("sys.stdin", stdin))
            return self.run_main("escalate", self.job_id)

    def test_escalate_moves_review_to_needs_human_before_the_last_round(self):
        self.in_review()
        self.review(self.job_id, "code", ["a.py:3 untagged"])
        self.assertEqual(self.current()["round"], 1)
        self.escalate()
        job = self.job.load(self.job_id)
        self.assertEqual(job["stage"], "needs-human")
        self.assertIn("Reviewer keeps writing untagged", (self.d / "decision.md").read_text())
        self.assertEqual((self.d / "decision.md").read_text().split("\n")[0], "ESCALATE")
        self.assertTrue(self.gh_calls("issue", "comment") or self.gh_calls("pr", "comment"))

    def test_escalate_outside_review_dies(self):
        with self.assertRaises(SystemExit):
            self.escalate()

    def test_escalate_needs_a_reason(self):
        self.in_review()
        with self.assertRaises(SystemExit):
            self.escalate("  ")


if __name__ == "__main__":
    unittest.main()
