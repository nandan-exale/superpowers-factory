"""Fixes from the first real run: evidence block, merge labels. tests.test_pipeline checks the intake prompt."""

import contextlib
import io
import re
import shutil
import types
import unittest
from unittest import mock

from budget_case import BudgetCase

GATE_MD = """GATE: PASS
COMMIT: 6c404148

## Summary
- checks.sh passed in 0s

## Protected paths
None changed.

## checks.sh
Exit 0 in 0s. Last 80 lines of checks.log:

```
.....
OK
```
"""


class EvidenceBlockTest(BudgetCase):
    def test_closes_omitted_when_the_kept_body_already_closes_the_issue(self):
        self.in_review()
        self.pr_body = "Adds the widget.\n\nCloses #7\n"
        self.advance("approve")
        self.assertEqual(self.pr_body.count("Closes #7"), 1)
        self.assertIn("Adds the widget.", self.pr_body)

    def test_closes_kept_when_the_body_does_not_close_the_issue(self):
        self.in_review()
        self.pr_body = "Adds the widget. Closes #8, see #7.\n"
        self.advance("approve")
        block = self.pr_body[:self.pr_body.index("<!-- /factory evidence -->")]
        self.assertIn("Closes #7", block)

    def test_closes_url_of_another_repo_does_not_count(self):
        self.in_review()
        self.job._repo_slug = "o/r"
        self.pr_body = "Fixes https://github.com/x/y/issues/7\n"
        self.advance("approve")
        block = self.pr_body[:self.pr_body.index("<!-- /factory evidence -->")]
        self.assertIn("Closes #7", block)

    def test_closes_url_is_ignored_when_the_repo_is_unknown(self):
        self.in_review()
        self.job._repo_slug = None
        self.job.gh = lambda *a: (_ for _ in ()).throw(self.job.Refused("no gh")) \
            if a[:2] == ("repo", "view") else self.fake_gh(lambda *x: "", *a)
        self.pr_body = "Fixes https://github.com/o/r/issues/7\n"
        self.advance("approve")
        block = self.pr_body[:self.pr_body.index("<!-- /factory evidence -->")]
        self.assertIn("Closes #7", block)

    def test_closes_stays_single_across_republishing(self):
        self.in_review()
        self.job._repo_slug = "o/r"
        self.pr_body = "Fixes https://github.com/o/r/issues/7\n"
        self.advance("approve")
        self.job.publish_evidence(self.current())
        self.job.publish_evidence(self.current())
        self.assertEqual(len(re.findall(r"issues/7|Closes #7", self.pr_body)), 1)

    def test_closes_in_a_previous_block_alone_does_not_count(self):
        self.in_review()
        self.pr_body = "No body from the builder.\n"
        self.advance("approve")
        self.assertEqual(self.pr_body.count("Closes #7"), 1)
        self.job.publish_evidence(self.current())
        self.assertEqual(self.pr_body.count("Closes #7"), 1)

    def test_checks_headings_cannot_become_headings(self):
        self.in_review()
        (self.d / "round-1" / "checks.md").write_text(GATE_MD)
        text = self.job.evidence_md(self.current())
        inside, fence = False, None
        for line in text.splitlines():
            if fence is None and re.match(r"`{3,}$", line):
                fence = line
            elif fence is not None and line == fence:
                fence = None
            elif fence is None and line.startswith("#"):
                self.assertTrue(line.startswith(("## Factory evidence", "### ")), line)
        self.assertIsNone(fence)

    def test_diffstat_keeps_its_leading_space(self):
        self.in_review()
        self.job.git = lambda *a, **k: types.SimpleNamespace(stdout=" a.py | 2 +-\n 1 file changed\n")
        text = self.job.evidence_md(self.current())
        self.assertIn("### Files changed\n```\n a.py | 2 +-\n 1 file changed\n```\n", text)


class MergeTest(BudgetCase):
    def to_approve(self, planned=True):
        self.in_review(planned=planned)
        self.advance("approve")

    def merge(self):
        ok = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        self.job.git = lambda job, *a, **k: ok
        self.job.subprocess = types.SimpleNamespace(run=lambda *a, **k: ok)
        self.job.gh_api_list = lambda path: []
        self.job.pr_comments = lambda job: []
        merged = []

        def gh_json(*args):
            if args[:2] == ("pr", "view"):
                return {"state": "MERGED" if merged else "OPEN", "isDraft": False, "body": self.pr_body}
            return self.fake_gh_json(*args)
        self.job.gh_json = gh_json
        record = self.job.gh

        def gh(*args):
            if args[:2] == ("issue", "edit") and getattr(self, "label_error", False):
                raise self.job.Refused("gh is down")
            if args[:2] == ("pr", "merge"):
                merged.append(True)
            return record(*args)
        self.job.gh = gh
        (self.d / "decision.md").write_text("APPROVE\n\n## Why\nfine\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.job.cmd_merge(self.job.load(self.job_id))
        return self.job.load(self.job_id)

    def test_merge_pulls_the_main_checkout(self):
        self.to_approve()
        pulled = []
        self.job.sync_main = lambda: pulled.append(True)
        job = self.merge()
        self.assertEqual(job["stage"], "merged")
        self.assertEqual(pulled, [True])

    def test_merge_republishes_evidence_with_the_final_cost_before_merging(self):
        self.cost = 1.0
        self.to_approve()
        self.assertIn("cost $1.00", self.pr_body)
        self.cost = 3.5  # the approver ran after the first publish
        job = self.merge()
        self.assertEqual(job["stage"], "merged")
        calls = [c[:2] for c in self.project.gh_calls if c[0] == "pr"]
        self.assertLess(len(calls) - 1 - calls[::-1].index(("pr", "edit")),
                        calls.index(("pr", "merge")))
        self.assertIn("cost $3.50", self.pr_body)

    def test_failed_republish_does_not_stop_the_merge(self):
        self.to_approve()
        self.edit_error = "gh is down"
        with mock.patch("sys.stderr"):
            job = self.merge()
        self.assertEqual(job["stage"], "merged")

    def test_merged_issue_loses_its_queue_labels(self):
        self.to_approve()
        job = self.merge()
        self.assertEqual(job["stage"], "merged")
        self.assertIn(("issue", "edit", "7", "--remove-label", "factory,factory:planned"),
                      self.project.gh_calls)

    def test_label_failure_does_not_block_the_merge(self):
        self.to_approve()
        self.label_error = True
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            job = self.merge()
        self.assertEqual(job["stage"], "merged")
        self.assertIn("job: labels not removed:", err.getvalue())

    def test_queue_sweep_survives_label_failure(self):
        self.to_approve()
        self.issues = [{"number": 9, "title": "Another"}]
        self.in_review(planned=True)
        self.job.save({**self.job.load(self.job_id), "stage": "approve"})
        self.label_error = True
        shutil.rmtree(self.job.load(self.job_id)["worktree"])  # a test stand-in, not a real worktree
        self.job.gh_json = lambda *a: ({"state": "MERGED", "isDraft": False, "body": ""}
                                       if a[:2] == ("pr", "view") else self.fake_gh_json(*a))
        record = self.job.gh

        def gh(*args):
            if args[:2] == ("issue", "edit"):
                raise self.job.Refused("gh is down")
            return record(*args)
        self.job.gh = gh
        out = io.StringIO()
        with mock.patch("sys.stderr", new_callable=io.StringIO), contextlib.redirect_stdout(out):
            self.job.cmd_queue()
        self.assertEqual(self.job.load(self.job_id)["stage"], "merged")
        self.assertIn("new\t9", out.getvalue())

    def test_merged_unplanned_issue_loses_only_the_queue_label(self):
        self.to_approve(planned=False)
        job = self.merge()
        self.assertEqual(job["stage"], "merged")
        self.assertIn(("issue", "edit", "7", "--remove-label", "factory"), self.project.gh_calls)


if __name__ == "__main__":
    unittest.main()
