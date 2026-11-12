import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from factory_project import FactoryProject

AGENTS = {
    "spec-writer": {"model": "opus", "effort": "high"},
    "builder": {"model": "opus", "effort": "high"},
    "approver": {"model": "opus", "effort": "high"},
    "reviewers": {"code": {"model": "haiku", "effort": "medium"}},
}


def gh_comment(cid, body, login="operator", kind="User", **extra):
    return {"id": cid, "body": body, "user": {"login": login, "type": kind},
            "html_url": f"https://github.com/o/r/pull/12#c{cid}",
            "created_at": f"2026-11-12T10:00:{cid:02d}Z", **extra}


class PrFeedbackTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp.name
        self.project = FactoryProject(self.tmp.name)
        self.project.set_issue("Build the widget.", labels=("factory",))
        self.job = self.project.load_job()
        self.job_id = self.project.create_job(self.job)
        self.d = self.job.job_dir(self.job_id)
        self.fake_github()

    def tearDown(self):
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.tmp.cleanup()

    def fake_github(self, comments=(), inline=(), reviews=(), issues=()):
        def gh_json(*args):
            if args[0] == "api":
                path = args[1].split("?")[0]
                if "/issues/" in path:
                    return list(comments)
                return list(inline) if path.endswith("/comments") else list(reviews)
            if args[:2] == ("pr", "view"):
                return {"state": "OPEN", "isDraft": False}
            if args[:2] == ("issue", "list"):
                return list(issues)
            raise AssertionError(f"unexpected gh_json{args}")
        self.job.gh_json = gh_json

    def set_state(self, **fields):
        job = self.job.load(self.job_id)
        job.update({"pr": 12, "pr_url": "https://github.com/o/r/pull/12", "agents": AGENTS, **fields})
        self.job.save(job)
        rd = self.d / f"round-{job['round']}"
        rd.mkdir(exist_ok=True)
        Path(job["worktree"]).mkdir(parents=True, exist_ok=True)

    def current(self):
        return self.job.sync(self.job.load(self.job_id))

    def pr_feedback(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_pr_feedback(self.current())
        return out.getvalue().strip()

    def acks(self):
        return [c for c in self.project.gh_calls if c[:3] == ("pr", "comment", "12")]


class CollectTest(PrFeedbackTestCase):
    def setUp(self):
        super().setUp()
        self.set_state(stage="review", round=1)

    def test_collects_every_trusted_kind(self):
        self.fake_github(comments=[gh_comment(1, "Rename it to total.")],
                         inline=[gh_comment(2, "Off by one here.", path="calc.py", line=3)],
                         reviews=[gh_comment(3, "Needs a test for zero.", state="CHANGES_REQUESTED")])
        self.assertEqual(self.pr_feedback(), "PR-FEEDBACK: feedback-1.md (3 comments)")
        text = (self.d / "feedback-1.md").read_text()
        self.assertIn("## @operator, comment", text)
        self.assertIn("## @operator, inline on `calc.py:3`", text)
        self.assertIn("## @operator, review", text)
        self.assertIn("> Off by one here.", text)
        job = self.job.load(self.job_id)
        self.assertTrue(job["feedback_pending"])
        self.assertEqual(job["pr_feedback_seen"], ["comment-1", "inline-2", "review-3"])

    def test_skips_untrusted_and_empty(self):
        marker = self.job.MARKER
        self.fake_github(comments=[gh_comment(1, "lgtm", login="ci-bot", kind="Bot"),
                                   gh_comment(2, f"{marker}\n### Factory: needs a human"),
                                   gh_comment(3, "please add X", login="stranger")],
                         reviews=[gh_comment(4, "", state="APPROVED"),
                                  gh_comment(5, "draft thoughts", state="PENDING")])
        self.assertEqual(self.pr_feedback(), "PR-FEEDBACK: none")
        self.assertFalse((self.d / "feedback-1.md").exists())
        self.assertEqual(self.acks(), [])

    def test_allowed_list_from_config(self):
        self.job.CONFIG["pr_feedback"]["allowed"] = ["teammate"]
        self.fake_github(comments=[gh_comment(1, "Use a dict.", login="teammate")])
        self.assertEqual(self.pr_feedback(), "PR-FEEDBACK: feedback-1.md (1 comments)")

    def test_bad_allowed_config_refused(self):
        self.job.CONFIG["pr_feedback"]["allowed"] = "teammate"
        self.fake_github(comments=[gh_comment(1, "x")])
        with self.assertRaises(self.job.Refused) as ctx:
            self.pr_feedback()
        self.assertIn("pr_feedback.allowed", str(ctx.exception))

    def test_comment_handled_once(self):
        self.fake_github(comments=[gh_comment(1, "Rename it.")])
        self.pr_feedback()
        self.assertEqual(self.pr_feedback(), "PR-FEEDBACK: pending feedback-1.md")
        self.assertFalse((self.d / "feedback-2.md").exists())
        self.assertEqual(len(self.acks()), 1)
        self.assertIn("picked up 1 PR comment", self.acks()[0][4])

    def test_no_pr_means_none(self):
        self.set_state(stage="build", round=1, pr=None)
        self.assertEqual(self.pr_feedback(), "PR-FEEDBACK: none")


class FlowTest(PrFeedbackTestCase):
    def pass_reviews(self):
        (self.d / "round-1" / "review-code.md").write_text("VERDICT: PASS\n\n## Summary\n- ok\n")

    def test_needs_human_resumes_to_build(self):
        self.set_state(stage="needs-human", round=1)
        (self.d / "decision.md").write_text("ESCALATE\n\n## Why\nunsure\n")
        self.fake_github(comments=[gh_comment(1, "Go with option B.")])
        self.pr_feedback()
        job = self.job.load(self.job_id)
        self.assertEqual(job["stage"], "build")
        self.assertEqual(job["round"], 2)
        self.assertEqual(job["round_limit"], 2 + self.job.CONFIG["max_rounds"] - 1)
        self.assertFalse(job["feedback_pending"])

    def test_review_pass_with_pending_goes_to_build(self):
        self.set_state(stage="review", round=1, feedback_pending=True)
        self.pass_reviews()
        with self.assertRaises(self.job.Refused) as ctx:
            self.job.advance(self.current(), "approve")
        self.assertIn("PR feedback", str(ctx.exception))
        job = self.job.advance(self.current(), "build")
        self.assertEqual(job["round"], 2)
        self.assertFalse(job["feedback_pending"])

    def test_review_pass_without_pending_refuses_build(self):
        self.set_state(stage="review", round=1)
        self.pass_reviews()
        with self.assertRaises(self.job.Refused) as ctx:
            self.job.advance(self.current(), "build")
        self.assertIn("every review passed", str(ctx.exception))

    def merge(self):
        (self.d / "decision.md").write_text("APPROVE\n\n## Why\nfine\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.job.cmd_merge(self.job.load(self.job_id))
        return self.job.load(self.job_id)

    def test_merge_blocked_by_pending_feedback(self):
        self.set_state(stage="approve", round=1, feedback_pending=True)
        job = self.merge()
        self.assertEqual(job["stage"], "needs-human")
        self.assertIn("PR comments", (self.d / "decision.md").read_text())

    def test_merge_blocked_by_new_comment(self):
        self.set_state(stage="approve", round=1)
        self.fake_github(comments=[gh_comment(1, "Wait, don't merge.")])
        self.assertEqual(self.merge()["stage"], "needs-human")

    def queue(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_queue()
        return out.getvalue()

    def test_queue_resumes_needs_human_with_comments(self):
        self.set_state(stage="needs-human", round=1)
        self.fake_github(comments=[gh_comment(1, "Option B.")], issues=[{"number": 7, "title": "Build the widget."}])
        self.assertIn(f"resume\t7\t{self.job_id}\tneeds-human\tPR feedback", self.queue())

    def test_queue_waits_without_comments(self):
        self.set_state(stage="needs-human", round=1)
        self.fake_github(issues=[{"number": 7, "title": "Build the widget."}])
        self.assertIn(f"wait\t7\t{self.job_id}\tneeds-human", self.queue())


if __name__ == "__main__":
    unittest.main()
