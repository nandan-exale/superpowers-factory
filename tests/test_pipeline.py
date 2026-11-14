import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "vendor" / "factory" / "factory" / "lib"))

from orchestrator import pipeline  # noqa: E402
from orchestrator.jobcli import Out  # noqa: E402
from orchestrator.pipeline import Done, Pipeline  # noqa: E402

CONFIG = {"base_branch": "main", "labels": {"planned": "factory:planned"},
          "ports": {"base": 5100, "step": 10}}


class FakeCli:
    """job/gate/route/gh answered from `answers` ({args tuple prefix: Out}); job.json from `jobs`."""

    def __init__(self, repo):
        self.repo = repo
        self.calls = []
        self.answers = {}
        self.jobs = {}

    def answer(self, *prefix, code=0, out="", err=""):
        self.answers[prefix] = Out(code, out, err)

    def _reply(self, args, stdin=None):
        self.calls.append((args, stdin))
        for n in range(len(args), 0, -1):
            if args[:n] in self.answers:
                return self.answers[args[:n]]
        if args[:2] == ("job", "agent"):
            return Out(0, "model=opus effort=high\n", "")
        return Out(0, "", "")

    def job(self, *args, stdin=None):
        return self._reply(("job", *map(str, args)), stdin)

    def gate(self, job_id):
        return self._reply(("gate", job_id))

    def route(self, job_id):
        return self._reply(("route", job_id))

    def gh(self, *args):
        return self._reply(("gh", *map(str, args)))

    def state(self, job_id):
        return self.jobs[job_id]

    def config(self):
        return CONFIG

    def called(self, *prefix):
        return [a for a, _ in self.calls if a[:len(prefix)] == prefix]


class PipelineCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.folder = self.repo / "factory" / "jobs" / "004-x"
        (self.folder / "round-1").mkdir(parents=True)
        self.cli = FakeCli(self.repo)
        self.lines = []
        self.p = Pipeline(self.cli, say=self.lines.append)
        self.cli.jobs["004-x"] = {"id": "004-x", "issue": 12, "stage": "intake", "round": 0,
                                  "worktree": str(self.repo / ".worktrees/004-x"), "branch": "factory/004-x",
                                  "pr": None, "agents": None, "reviews": {}}
        self.cli.answer("job", "ensure-worktree", "004-x", out="WORKTREE: 004-x present\n")

    def set(self, **fields):
        self.cli.jobs["004-x"] = {**self.cli.jobs["004-x"], **fields}

    def write(self, rel, text):
        (self.folder / rel).write_text(text)

    def done(self, spawn, ok=True, session=None, note=""):
        return Done(spawn, ok, session, note)

    def only(self, spawns):
        self.assertEqual(len(spawns), 1, spawns)
        return spawns[0]


class StartTest(PipelineCase):
    def test_new_issue_goes_to_intake_in_the_main_checkout(self):
        self.cli.answer("job", "create", "12", out="004-x\n")
        self.cli.answer("gh", "issue", "view", out="factory\n")
        job_id, spawns = self.p.begin(("new", "12", "-", "-", "Title"))
        s = self.only(spawns)
        self.assertEqual((job_id, s.role, s.cwd, s.own), ("004-x", "intake", self.repo, ("intake.md",)))
        self.assertIn("Worktree: none, it doesn't exist yet.", s.prompt)
        self.assertEqual((s.model, s.effort), ("opus", "high"))

    def test_planned_issue_skips_intake_and_builds(self):
        self.cli.answer("gh", "issue", "view", out="factory\nfactory:planned\n")
        self.cli.answer("job", "planned", "004-x", out="PLANNED: 004-x → build (code)\n")
        self.set(stage="build", round=1)
        _, spawns = self.p.begin(("resume", "12", "004-x", "intake", "round 0"))
        s = self.only(spawns)
        self.assertEqual(s.role, "builder")
        self.assertTrue(s.prompt.endswith("Build round 1. Port: 5140."))
        self.assertIsNone(s.resume)

    def test_refused_plan_finishes_the_job(self):
        self.cli.answer("gh", "issue", "view", out="factory:planned\n")
        self.cli.answer("job", "planned", "004-x", out="PLANNED: REFUSED bad block\n")
        self.assertEqual(self.p.begin(("resume", "12", "004-x", "intake", ""))[1], [])
        self.assertIn("PLANNED: REFUSED bad block", self.lines)

    def test_resume_build_resumes_the_stored_session(self):
        self.set(stage="build", round=2, sessions={"builder": "sess-1"})
        s = self.only(self.p.begin(("resume", "12", "004-x", "build", "round 2"))[1])
        self.assertEqual(s.resume, "sess-1")
        self.assertIn(pipeline.prompts.RESUMING, s.prompt)
        self.assertIn(pipeline.prompts.RESUMING, s.fresh_prompt)

    def test_resume_build_names_feedback_newer_than_build_md(self):
        # `/factory` feedback moves the job to build; the resumed builder must be told to read it.
        self.set(stage="build", round=2)
        for rel, age in (("feedback-1.md", 300), ("build.md", 200), ("feedback-2.md", 0)):
            self.write(rel, "x\n")
            when = time.time() - age
            os.utime(self.folder / rel, (when, when))
        s = self.only(self.p.begin(("resume", "12", "004-x", "build", "round 2"))[1])
        self.assertIn(pipeline.prompts.feedback(["feedback-2.md"], 2), s.prompt)
        self.assertNotIn("feedback-1.md", s.prompt)

    def test_resume_review_spawns_only_missing_reviewers(self):
        self.set(stage="review", round=1, agents={"reviewers": {"code": {}, "ux": {}}})
        self.write("round-1/review-code.md", "VERDICT: PASS\n")
        s = self.only(self.p.begin(("resume", "12", "004-x", "review", ""))[1])
        self.assertEqual((s.role, s.own), ("reviewer-ux", ("round-1/review-ux.md",)))
        self.assertTrue(s.prompt.endswith("Review round 1. Port: 5141."))

    def test_worktree_is_ensured_before_the_first_spawn(self):
        # Was the skill's "run factory/bin/job ensure-worktree <id>" before the first spawn.
        self.set(stage="spec")
        self.p.begin(("resume", "12", "004-x", "spec", ""))
        jobs = self.cli.called("job")
        self.assertLess(jobs.index(("job", "ensure-worktree", "004-x")),
                        jobs.index(("job", "agent", "004-x", "spec-writer")))

    def test_spec_writer_works_in_the_worktree_with_the_full_header(self):
        # Was the skill's intake and spec wording: only intake is told the worktree doesn't exist yet.
        self.set(stage="spec")
        s = self.only(self.p.begin(("resume", "12", "004-x", "spec", ""))[1])
        self.assertEqual(s.cwd, self.repo / ".worktrees/004-x")
        self.assertIn(f"Worktree: {self.repo / '.worktrees/004-x'}. ", s.prompt)
        self.assertIn("Base: origin/main.", s.prompt)  # base_branch from config.json

    def test_risk_ok_resume_goes_back_to_merging(self):
        # Was the skill's "A needs-human job with the note `factory:risk-ok added`".
        self.set(stage="needs-human")
        self.assertEqual(self.p.begin(("resume", "12", "004-x", "needs-human", "factory:risk-ok added"))[1], [])
        jobs = self.cli.called("job")
        self.assertLess(jobs.index(("job", "advance", "004-x", "merging")), jobs.index(("job", "merge", "004-x")))

    def test_lost_worktree_finishes_the_job(self):
        self.set(stage="spec")
        self.cli.answer("job", "ensure-worktree", "004-x", out="004-x: needs-human: worktree gone\n")
        self.assertEqual(self.p.begin(("resume", "12", "004-x", "spec", ""))[1], [])


class AfterTest(PipelineCase):
    def spawn(self, role, own=("x",), prompt="P"):
        return pipeline.Spawn("004-x", role, prompt, self.repo, self.folder, own)

    def test_intake_accept_routes_and_spawns_the_spec_writer(self):
        self.write("intake.md", "DECISION: ACCEPT\nRISK: low\n\nbody\n")
        self.cli.answer("job", "advance", "004-x", "spec", out="004-x: spec (round 0)\n")
        s = self.only(self.p.after("004-x", [self.done(self.spawn("intake"))]))
        self.assertEqual((s.role, s.own), ("spec-writer", ("spec.md",)))
        self.assertEqual(self.cli.called("route"), [("route", "004-x")])

    def test_intake_with_a_bad_decision_is_asked_once_then_escalated(self):
        self.write("intake.md", "DECISION: MAYBE\n")
        again = self.only(self.p.after("004-x", [self.done(self.spawn("intake", ("intake.md",)))]))
        self.assertIn("The factory refused your result", again.prompt)
        self.assertEqual(self.p.after("004-x", [self.done(again)]), [])
        self.assertEqual(len(self.cli.called("job", "escalate", "004-x")), 1)

    def test_builder_ready_gate_pass_spawns_reviewers_with_ports(self):
        self.write("build.md", "STATUS: READY\n")
        self.set(stage="build", round=1, agents={"reviewers": {"code": {}, "ui": {}}})
        self.cli.answer("gate", "004-x", out="GATE: PASS (004-x round 1, …)\n")
        spawns = self.p.after("004-x", [self.done(self.spawn("builder"), session="sess-9")])
        self.assertEqual([s.role for s in spawns], ["reviewer-code", "reviewer-ui"])
        self.assertTrue(spawns[1].prompt.endswith("Port: 5142."))
        self.assertIn(("job", "set-session", "004-x", "builder", "sess-9"), self.cli.called("job"))
        self.assertIn(("job", "advance", "004-x", "gate"), self.cli.called("job"))
        self.assertIn(("job", "advance", "004-x", "review"), self.cli.called("job"))

    def test_gate_fail_sends_the_builder_back_with_pr_comments(self):
        self.write("build.md", "STATUS: READY\n")
        self.set(stage="build", round=1, sessions={"builder": "sess-9"})
        self.cli.answer("gate", "004-x", code=1, out="GATE: FAIL (004-x round 1)\n")
        self.cli.answer("job", "pr-feedback", "004-x", out="PR-FEEDBACK: feedback-1.md (1 new comments)\n")
        s = self.only(self.p.after("004-x", [self.done(self.spawn("builder"))]))
        self.assertEqual(s.resume, "sess-9")
        self.assertIn(pipeline.prompts.gate_failed(1), s.prompt)
        self.assertIn("Also address PR comments in feedback-1.md.", s.prompt)

    def test_gate_fail_in_the_last_round_goes_to_needs_human(self):
        self.write("build.md", "STATUS: READY\n")
        self.set(stage="build", round=3)
        self.cli.answer("gate", "004-x", code=1, out="GATE: FAIL\n")
        self.cli.answer("job", "advance", "004-x", "build", code=1, err="job: round 3 of 3: go to needs-human")
        self.assertEqual(self.p.after("004-x", [self.done(self.spawn("builder"))]), [])
        self.assertIn(("job", "advance", "004-x", "needs-human"), self.cli.called("job"))

    def test_builder_blocked_goes_to_needs_human(self):
        self.write("build.md", "STATUS: BLOCKED\n")
        self.assertEqual(self.p.after("004-x", [self.done(self.spawn("builder"))]), [])
        self.assertIn(("job", "advance", "004-x", "needs-human"), self.cli.called("job"))

    def test_reviews_all_pass_spawn_the_approver(self):
        self.set(stage="review", round=2, pr=30, reviews={"code": "PASS"})
        s = self.only(self.p.after("004-x", [self.done(self.spawn("reviewer-code"))]))
        self.assertEqual((s.role, s.own), ("approver", ("decision.md",)))
        self.assertTrue(s.prompt.endswith("PR: #30. Final round: 2."))

    def test_review_changes_send_the_builder_back(self):
        self.set(stage="review", round=1, reviews={"code": "CHANGES"})
        s = self.only(self.p.after("004-x", [self.done(self.spawn("reviewer-code"))]))
        self.assertEqual(s.role, "builder")
        self.assertIn(pipeline.prompts.changes(1, 2), s.prompt)

    def test_invalid_review_is_redone_once_then_escalated(self):
        self.set(stage="review", round=1, reviews={"code": "invalid"})
        self.cli.answer("job", "advance", "004-x", code=1, err="job: review-code.md has no VERDICT line")
        again = self.only(self.p.after("004-x", [self.done(self.spawn("reviewer-code"))]))
        self.assertEqual(again.role, "reviewer-code")
        self.assertIn("no VERDICT line", again.prompt)
        self.assertEqual(self.p.after("004-x", [self.done(again)]), [])
        self.assertEqual(len(self.cli.called("job", "escalate", "004-x")), 1)

    def test_approve_merges_and_escalate_goes_to_needs_human(self):
        self.write("decision.md", "APPROVE\n")
        self.assertEqual(self.p.after("004-x", [self.done(self.spawn("approver"))]), [])
        self.assertEqual(self.cli.called("job", "merge"), [("job", "merge", "004-x")])
        self.write("decision.md", "ESCALATE\n")
        self.p.after("004-x", [self.done(self.spawn("approver"))])
        self.assertIn(("job", "advance", "004-x", "needs-human"), self.cli.called("job"))

    def test_failed_agent_escalates_with_its_note(self):
        self.assertEqual(self.p.after("004-x", [self.done(self.spawn("spec-writer"), ok=False,
                                                          note="exit 1 twice")]), [])
        (args, stdin), = [(a, s) for a, s in self.cli.calls if a[:2] == ("job", "escalate")]
        self.assertIn("spec-writer: exit 1 twice", stdin)

    def test_budget_stop_ends_the_job(self):
        self.write("build.md", "STATUS: READY\n")
        self.cli.answer("job", "advance", "004-x", "gate", out="BUDGET: 004-x → needs-human (budget: $30 of $25)\n")
        self.assertEqual(self.p.after("004-x", [self.done(self.spawn("builder"))]), [])
        self.assertIn("BUDGET: 004-x → needs-human (budget: $30 of $25)", self.lines)

    def test_daily_budget_stops_the_job_and_flags_the_run(self):
        self.write("spec.md", "spec")
        self.cli.answer("job", "advance", "004-x", "build", code=1, err="job: daily budget: $100 of $100")
        with self.assertRaises(pipeline.Stop):
            self.p.after("004-x", [self.done(self.spawn("spec-writer"))])
        self.assertTrue(self.p.daily)


class LearnTest(PipelineCase):
    def test_learn_spawns_a_learner_per_tag(self):
        self.cli.answer("job", "learn", out="LEARN: other:x (3 jobs) factory/jobs/learning/other--x/evidence.md\n")
        s = self.only(self.p.learn())
        self.assertEqual((s.job_id, s.role, s.own), ("other:x", "learner", ("proposal.md",)))
        self.assertEqual(s.folder, self.repo / "factory" / "jobs" / "learning" / "other--x")
        self.assertEqual(s.prompt, f"Job folder: {self.repo}/factory/jobs/learning/other--x/. other:x")
        self.assertIn(("job", "agent", "other:x", "learner"), self.cli.called("job"))

    def test_after_learner_files_the_proposal(self):
        self.cli.answer("job", "learn-file", "other:x", out="LEARN-FILE: other:x #42\n")
        s = pipeline.Spawn("other:x", "learner", "P", self.repo, self.folder, ("proposal.md",))
        self.assertEqual(self.p.after("other:x", [Done(s, True)]), [])
        self.assertEqual(self.p.learn_files, ["LEARN-FILE: other:x #42"])


if __name__ == "__main__":
    unittest.main()
