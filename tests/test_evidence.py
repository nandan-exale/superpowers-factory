import contextlib
import io
import types
import unittest

from budget_case import BudgetCase

HEADINGS = ("### Files changed", "### Checks", "### Acceptance criteria",
            "### Plan tasks and deviations", "### Reviews", "### Budget")

BUILD_MD = """STATUS: READY

## Summary
- spins

## Acceptance criteria
1. [x] spins: test_spin passes

## Plan tasks
- [x] Task 1: Spin

## Deviations
None.
"""


class EvidenceTest(BudgetCase):
    def test_full_job_has_every_section(self):
        self.in_review(planned=True)
        (self.d / "build.md").write_text(BUILD_MD)
        (self.d / "round-1" / "checks.md").write_text("GATE: PASS\nCOMMIT: abc\n\nok 1\nok 2\n")
        text = self.job.evidence_md(self.current())
        self.assertTrue(text.startswith("<!-- factory evidence -->\n"))
        for heading in HEADINGS:
            self.assertIn(heading, text)
        self.assertIn("GATE: PASS", text)
        self.assertIn("ok 2", text)
        self.assertIn("1. [x] spins: test_spin passes", text)
        self.assertIn("- [x] Task 1: Spin", text)
        self.assertIn("- code — PASS", text)
        self.assertIn("Rounds 1 of 3", text)
        self.assertIn("of $25.00", text)
        self.assertIn("Closes #7", text)

    def test_missing_files_give_explicit_lines(self):
        text = self.job.evidence_md(self.current())
        self.assertIn("### Files changed\nnone", text)
        self.assertIn("### Checks\nnot run", text)
        self.assertIn("### Acceptance criteria\nnone recorded", text)
        self.assertIn("### Plan tasks and deviations\nnot a planned job", text)
        self.assertIn("### Reviews\nnone", text)

    def test_no_limits_say_so(self):
        self.job.CONFIG["budgets"].update(job_usd=None, job_hours=None)
        text = self.job.evidence_md(self.current())
        self.assertIn("of no limit", text)

    def test_entering_approve_replaces_pr_body(self):
        self.in_review()
        self.advance("approve")
        edits = self.gh_calls("pr", "edit", "12")
        self.assertEqual(len(edits), 1)
        self.assertIn("--body-file", edits[0])
        self.assertTrue((self.d / "evidence.md").exists())

    def test_budget_stop_publishes_evidence(self):
        self.in_review()
        self.cost = 30.0
        self.advance("approve")
        self.assertEqual(len(self.gh_calls("pr", "edit", "12")), 1)

    def test_normal_escalation_publishes_evidence(self):
        self.in_review(round=3)
        rd = self.d / "round-3"
        rd.mkdir()
        (rd / "review-code.md").write_text("VERDICT: CHANGES\n")
        self.assertEqual(self.advance("needs-human")["stage"], "needs-human")
        self.assertEqual(len(self.gh_calls("pr", "edit", "12")), 1)

    def test_failed_publish_does_not_block_the_transition(self):
        self.in_review()
        self.edit_error = "gh is down"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.run_main("advance", self.job_id, "approve")
        self.assertIn("job: evidence not published: gh is down", err.getvalue())
        saved = self.job.load(self.job_id)
        self.assertEqual(saved["stage"], "approve")
        self.assertEqual(saved["evidence_error"], "gh is down")
        self.edit_error = None
        self.job.save(self.job.sync(saved))
        self.job.publish_evidence(saved)
        self.assertNotIn("evidence_error", saved)

    def test_huge_sections_are_truncated_in_the_body_only(self):
        self.in_review()
        (self.d / "build.md").write_text("STATUS: READY\n\n## Acceptance criteria\n" + "x" * 100_000 + "\n")
        self.advance("approve")
        self.assertLessEqual(len(self.pr_body), 60_000)
        self.assertIn("truncated; full text in factory/jobs/", self.pr_body)
        self.assertGreater(len((self.d / "evidence.md").read_text()), 100_000)
        self.assertIn("<!-- /factory evidence -->", self.pr_body)

    def test_whole_block_is_capped(self):
        self.in_review(planned=True)
        big = "y" * 7_900
        (self.d / "build.md").write_text(
            f"STATUS: READY\n\n## Acceptance criteria\n{big}\n\n## Plan tasks\n{big}\n\n## Deviations\n{big}\n")
        (self.d / "round-1" / "checks.md").write_text("GATE: PASS\n\n" + "z" * 7_900 + "\n")
        self.job.EVIDENCE_BLOCK_LIMIT = 10_000
        self.advance("approve")
        self.assertLessEqual(len(self.pr_body), 10_000)
        self.assertIn("truncated", self.pr_body)
        self.assertTrue(self.pr_body.rstrip().endswith("<!-- /factory evidence -->"))

    def test_existing_pr_body_is_kept_and_block_replaced_not_duplicated(self):
        self.in_review()
        self.pr_body = "Closes #7\n\nHuman notes"
        self.advance("approve")
        first = self.pr_body
        self.assertTrue(first.startswith("<!-- factory evidence -->"))
        self.assertTrue(first.rstrip().endswith("<!-- /factory evidence -->\n\nCloses #7\n\nHuman notes"))
        self.job.publish_evidence(self.current())
        self.assertEqual(self.pr_body.count("<!-- factory evidence -->"), 1)
        self.assertIn("Human notes", self.pr_body)
        self.assertEqual(self.pr_body.count("Human notes"), 1)

    def test_agent_text_is_defused(self):
        self.in_review()
        (self.d / "build.md").write_text(
            "STATUS: READY\n\n## Acceptance criteria\nFixes #42 and resolved: o/r#9, thanks @someone <!-- x\n")
        text = self.job.evidence_md(self.current())
        self.assertIn("`Fixes #42`", text)
        self.assertIn("`resolved: o/r#9`", text)
        self.assertIn("@\u200bsomeone", text)
        self.assertNotIn("<!-- x", text)

    def test_code_fence_in_checks_does_not_break_out(self):
        self.in_review()
        (self.d / "round-1" / "checks.md").write_text("GATE: PASS\n\n```\nCloses #5\n````\n")
        text = self.job.evidence_md(self.current())
        self.assertIn("\n`````\nGATE: PASS\n\n```\n", text)
        self.assertIn("`Closes #5`", text)
        after = text.split("`````\n")[-1]
        self.assertTrue(after.startswith("\n### Acceptance criteria"))

    def test_closing_keyword_before_issue_url_is_defused(self):
        self.in_review()
        (self.d / "build.md").write_text(
            "STATUS: READY\n\n## Acceptance criteria\nFixes https://github.com/o/r/issues/3 ok\n")
        text = self.job.evidence_md(self.current())
        self.assertIn("`Fixes https://github.com/o/r/issues/3`", text)

    def test_unclosed_fence_in_a_section_cannot_swallow_the_rest(self):
        self.in_review()
        (self.d / "build.md").write_text("STATUS: READY\n\n## Acceptance criteria\n```python\nx = 1\n")
        text = self.job.evidence_md(self.current())
        before = text[:text.index("\nCloses #7")]
        fences = [line for line in before.splitlines() if line.startswith("```")]
        self.assertEqual(len(fences) % 2, 0)

    def test_files_changed_is_defused_and_fenced(self):
        self.in_review()
        stat = types.SimpleNamespace(stdout="Fixes #9 | 2 +-\n")
        self.job.git = lambda *a, **k: stat
        text = self.job.evidence_md(self.current())
        self.assertIn("### Files changed\n```\n`Fixes #9` | 2 +-\n```\n", text)

    def test_budget_line_uses_the_allowance(self):
        self.in_review(budget_base_usd=20.0)
        self.cost = 30.0
        text = self.job.evidence_md(self.current())
        self.assertIn("cost $10.00 of $25.00 since the last allowance ($30.00 total)", text)
        self.assertIn("since the last allowance", text.split("time ")[1])

    def test_budget_line_ends_with_cost_by_model(self):
        self.in_review()
        text = self.job.evidence_md(self.current())
        self.assertIn(" h since the last allowance · by model: none\n", text)

    def test_evidence_command_without_pr_writes_file_only(self):
        out = self.run_main("evidence", self.job_id)
        self.assertTrue((self.d / "evidence.md").exists())
        self.assertEqual(self.gh_calls("pr", "edit"), [])
        self.assertIn("evidence.md", out)


if __name__ == "__main__":
    unittest.main()
