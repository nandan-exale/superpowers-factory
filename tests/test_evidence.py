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

    def test_evidence_command_without_pr_writes_file_only(self):
        out = self.run_main("evidence", self.job_id)
        self.assertTrue((self.d / "evidence.md").exists())
        self.assertEqual(self.gh_calls("pr", "edit"), [])
        self.assertIn("evidence.md", out)


if __name__ == "__main__":
    unittest.main()
