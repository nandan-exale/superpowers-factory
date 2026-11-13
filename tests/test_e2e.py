import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from e2e_sandbox import E2ESandbox, git
from script_loader import load_script

PLUGIN = Path(__file__).resolve().parents[1]


class E2ECase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.e2e = load_script(PLUGIN / "scripts" / "e2e", f"e2e_{id(self)}")
        self.sb = E2ESandbox(self.tmp / "sb")

    def guard(self, **env):
        with mock.patch.dict(os.environ, self.sb.env(**env)):
            return self.e2e.guard(self.sb.repo)


class GithubRepoTest(E2ECase):
    def test_parses_https_ssh_and_scp_remotes(self):
        for url in ("https://github.com/A/factory-e2e.git", "ssh://git@github.com/a/factory-e2e",
                    "git@github.com:a/factory-e2e.git"):
            self.assertEqual(self.e2e.github_repo(url), "a/factory-e2e", url)

    def test_other_hosts_and_paths_are_none(self):
        for url in ("https://gitlab.com/a/b.git", "/tmp/x.git", ""):
            self.assertIsNone(self.e2e.github_repo(url), url)


class GuardTest(E2ECase):
    def test_a_good_sandbox_passes(self):
        self.assertEqual(self.guard(), "tester/factory-e2e")

    def test_refuses_the_plugins_own_repo(self):
        own = git(PLUGIN, "remote", "get-url", "origin")
        if self.e2e.github_repo(own) is None:
            self.skipTest("this checkout's origin isn't on github.com")
        git(self.sb.repo, "remote", "set-url", "origin", own)
        with self.assertRaisesRegex(self.e2e.Refused, "this plugin's repo"):
            self.guard()

    def test_refuses_a_name_without_e2e_or_sandbox(self):
        git(self.sb.repo, "remote", "set-url", "origin", "https://github.com/tester/real-app.git")
        with self.assertRaisesRegex(self.e2e.Refused, "must contain 'e2e' or 'sandbox'"):
            self.guard()

    def test_refuses_a_non_github_origin(self):
        git(self.sb.repo, "remote", "set-url", "origin", "https://gitlab.com/tester/factory-e2e.git")
        with self.assertRaisesRegex(self.e2e.Refused, "github.com"):
            self.guard()

    def test_refuses_without_the_factory(self):
        (self.sb.repo / "factory" / "bin" / "job").unlink()
        git(self.sb.repo, "commit", "-qam", "drop job")
        with self.assertRaisesRegex(self.e2e.Refused, "isn't installed"):
            self.guard()

    def test_refuses_a_dirty_tree(self):
        (self.sb.repo / "stray.txt").write_text("x")
        with self.assertRaisesRegex(self.e2e.Refused, "working tree has changes"):
            self.guard()

    def test_refuses_when_not_on_the_base_branch(self):
        git(self.sb.repo, "checkout", "-q", "-b", "other")
        with self.assertRaisesRegex(self.e2e.Refused, "not 'main'"):
            self.guard()

    def test_refuses_when_gh_is_logged_out(self):
        with self.assertRaisesRegex(self.e2e.Refused, "gh auth"):
            self.guard(FAKE_GH_AUTH_EXIT=1)

    def test_refuses_when_doctor_fails(self):
        with self.assertRaisesRegex(self.e2e.Refused, "doctor"):
            self.guard(FAKE_DOCTOR_EXIT=1)


class ConfigTest(E2ECase):
    def test_deep_merge_recurses_and_leaves_inputs_alone(self):
        base = {"budgets": {"job_usd": 25, "daily_usd": 100}, "base_branch": "main"}
        merged = self.e2e.deep_merge(base, {"budgets": {"job_usd": 0.05}, "x": [1]})
        self.assertEqual(merged, {"budgets": {"job_usd": 0.05, "daily_usd": 100}, "base_branch": "main", "x": [1]})
        self.assertEqual(base["budgets"]["job_usd"], 25)

    def test_scenario_config_forces_the_daily_budget(self):
        cfg = self.e2e.scenario_config({"budgets": {"daily_usd": 100}}, {"budgets": {"daily_usd": 999}}, 7.456)
        self.assertEqual(cfg["budgets"]["daily_usd"], 7.46)


class SpendTest(E2ECase):
    def write_log(self, job, *entries):
        d = self.sb.repo / "factory" / "jobs" / job
        d.mkdir(parents=True, exist_ok=True)
        with (d / "log.jsonl").open("a") as f:
            for t, usd in entries:
                f.write(json.dumps({"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "delta_usd": usd}) + "\n")

    def test_log_spend_counts_lines_since_a_time_in_every_log(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        self.write_log("001-a", (now - timedelta(hours=2), 5.0), (now, 1.25))
        self.write_log("learning", (now, 0.5))
        with (self.sb.repo / "factory/jobs/001-a/log.jsonl").open("a") as f:
            f.write('{"t": "2026-')  # a torn line being written right now
        self.assertEqual(self.e2e.log_spend(self.sb.repo / "factory" / "jobs", now), 1.75)

    def test_spend_adds_sessions_to_logs_and_counts_down_the_cap(self):
        jobs = self.sb.repo / "factory" / "jobs"
        spend = self.e2e.Spend(jobs, 2.0)
        self.write_log("001-a", (spend.start, 0.5))
        spend.add_session(0.25)
        self.assertEqual(spend.total(), 0.75)
        self.assertEqual(spend.remaining(), 1.25)
        spend.add_session(5)
        self.assertEqual(spend.remaining(), 0.0)


REVIEW = """VERDICT: CHANGES

## Summary
- one

## Findings
1. [missing-test] app.py:3 add a test
2. [other:naming] app.py:9 rename x
3. no tag here

## Notes
1. [secrets] a note, not a finding
"""


class ExpectTest(E2ECase):
    def ctx(self, stage="merged", review=REVIEW, **extra):
        jobs = self.tmp / "jobs"
        job_dir = jobs / "001-e2e"
        (job_dir / "round-1").mkdir(parents=True, exist_ok=True)
        (job_dir / "round-1" / "review-code.md").write_text(review)
        job = {"id": "001-e2e", "stage": stage}
        return {"job": job, "job_dir": job_dir, "jobs_dir": jobs,
                "tags": {"missing-test", "secrets"}, "stdout": "", **extra}

    def test_stage_as_value_or_list(self):
        self.assertEqual(self.e2e.check_expect({"stage": "merged"}, self.ctx()), [])
        self.assertEqual(self.e2e.check_expect({"stage": ["needs-human", "merged"]}, self.ctx()), [])
        self.assertEqual(len(self.e2e.check_expect({"stage": "rejected"}, self.ctx())), 1)

    def test_stage_not_needs_a_job(self):
        self.assertEqual(self.e2e.check_expect({"stage_not": ["intake"]}, self.ctx(stage="build")), [])
        self.assertEqual(len(self.e2e.check_expect({"stage_not": ["intake"]}, self.ctx(job=None))), 1)

    def test_findings_and_tags(self):
        ctx = self.ctx()
        self.assertEqual(self.e2e.check_expect({"min_findings": 3, "tags_any": ["other:*"]}, ctx), [])
        self.assertEqual(len(self.e2e.check_expect({"min_findings": 4}, ctx)), 1)
        self.assertEqual(len(self.e2e.check_expect({"review_tags_valid": True}, ctx)), 1)
        self.assertEqual(len(self.e2e.check_expect({"tags_any": ["secrets"]}, ctx)), 1)
        clean = REVIEW.replace("3. no tag here\n", "")
        self.assertEqual(self.e2e.check_expect({"review_tags_valid": True}, self.ctx(review=clean)), [])

    def test_decision_and_budget(self):
        ctx = self.ctx(stage="needs-human")
        (ctx["job_dir"] / "decision.md").write_text("\nESCALATE\n\n## Why\nbudget\n")
        ctx["job"]["budget_stopped"] = "job_usd 0.05 reached"
        self.assertEqual(self.e2e.check_expect({"decision_prefix": "ESCALATE", "budget_stopped": True}, ctx), [])
        del ctx["job"]["budget_stopped"]
        self.assertEqual(len(self.e2e.check_expect({"budget_stopped": True}, ctx)), 1)

    def test_files_and_first_lines_under_the_jobs_folder(self):
        ctx = self.ctx()
        proposal = ctx["jobs_dir"] / "learning" / "convention" / "proposal.md"
        proposal.parent.mkdir(parents=True)
        proposal.write_text("PROPOSAL: lint rule for x\n")
        expect = {"files": ["{job}/round-1/review-code.md", "learning/*/proposal.md"],
                  "first_lines": {"learning/*/proposal.md": "PROPOSAL:"}}
        self.assertEqual(self.e2e.check_expect(expect, ctx), [])
        self.assertEqual(len(self.e2e.check_expect({"files": ["{job}/decision.md"]}, ctx)), 1)
        self.assertEqual(len(self.e2e.check_expect({"first_lines": {"learning/*/proposal.md": "NOPE"}}, ctx)), 1)

    def test_github_and_output_keys(self):
        ctx = self.ctx(issue_labels=["factory", "factory:needs-info"], pr_state="OPEN",
                       learning_issues=[12], runner_log="2026 ran exit=0 3s cost=$1.00\n", stdout="LEARN: none")
        expect = {"issue_labels": ["factory:needs-info"], "pr_state": "OPEN", "learning_issue": True,
                  "runner_log_contains": "ran exit=", "stdout_contains": "LEARN:"}
        self.assertEqual(self.e2e.check_expect(expect, ctx), [])
        ctx.update(issue_labels=[], pr_state="MERGED", learning_issues=[], runner_log="", stdout="")
        self.assertEqual(len(self.e2e.check_expect(expect, ctx)), 5)
