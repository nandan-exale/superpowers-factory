"""job tells the operator when a job starts waiting on them, through config's notify.command."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from factory_project import FactoryProject

# Appends one JSON line per run: the FACTORY_NOTIFY_* variables and any Claude token it was given.
RECORD = ("import json, os, sys\n"
          "env = {k: v for k, v in os.environ.items()"
          " if k.startswith(('FACTORY_NOTIFY_', 'CLAUDE_CODE_OAUTH'))}\n"
          "open(sys.argv[1], 'a').write(json.dumps(env) + '\\n')\n")


class NotifyCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.project.set_issue("Build the widget.", labels=("factory",))
        self.job = self.project.load_job()
        self.job_id = self.project.create_job(self.job)
        self.d = self.job.job_dir(self.job_id)
        self.record = Path(tmp.name) / "notify.jsonl"

    def use(self, *command):
        self.job.CONFIG["notify"] = {"command": list(command)}

    def record_calls(self):
        self.use(sys.executable, "-c", RECORD, str(self.record))

    def calls(self):
        if not self.record.exists():
            return []
        return [json.loads(line) for line in self.record.read_text().splitlines()]

    def notify(self, stage, **fields):
        job = {**self.job.load(self.job_id), **fields}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.notify_waiting(job, stage)
        return out.getvalue()


class NotifyWaitingTest(NotifyCase):
    def test_no_notify_key_runs_nothing(self):
        self.assertEqual(self.notify("needs-human"), "")
        self.assertEqual(self.calls(), [])

    def test_runs_the_command_with_the_job_s_details(self):
        (self.d / "decision.md").write_text("ESCALATE\n\n## Why\nThe runner changed.\nA human must look.\n")
        self.record_calls()
        self.assertEqual(self.notify("needs-human"), "")
        [env] = self.calls()
        self.assertEqual(env["FACTORY_NOTIFY_TITLE"], "Factory: #7 needs you")
        self.assertEqual(env["FACTORY_NOTIFY_STAGE"], "needs-human")
        self.assertEqual(env["FACTORY_NOTIFY_JOB"], self.job_id)
        self.assertEqual(env["FACTORY_NOTIFY_URL"], "https://github.com/o/r/issues/7")
        self.assertEqual(env["FACTORY_NOTIFY_MESSAGE"],
                         "needs-human: Build the widget\n\nThe runner changed.\nA human must look.")

    def test_the_pr_url_wins_over_the_issue_s(self):
        self.record_calls()
        self.notify("needs-human", pr=12, pr_url="https://github.com/o/r/pull/12")
        self.assertEqual(self.calls()[0]["FACTORY_NOTIFY_URL"], "https://github.com/o/r/pull/12")

    def test_needs_info_reads_the_intake_questions(self):
        (self.d / "intake.md").write_text("DECISION: NEEDS-INFO\n\n## Questions\n1. Which page size?\n")
        self.record_calls()
        self.notify("needs-info")
        self.assertEqual(self.calls()[0]["FACTORY_NOTIFY_MESSAGE"],
                         "needs-info: Build the widget\n\n1. Which page size?")

    def test_message_keeps_five_lines_of_200_characters(self):
        why = "\n".join(f"{n}" * 300 for n in range(1, 8))
        (self.d / "decision.md").write_text(f"ESCALATE\n\n## Why\n{why}\n")
        self.record_calls()
        self.notify("needs-human")
        lines = self.calls()[0]["FACTORY_NOTIFY_MESSAGE"].split("\n\n", 1)[1].splitlines()
        self.assertEqual(lines, [f"{n}" * 200 for n in range(1, 6)])

    def test_no_reason_file_sends_the_first_line_alone(self):
        self.record_calls()
        self.notify("needs-human")
        self.assertEqual(self.calls()[0]["FACTORY_NOTIFY_MESSAGE"], "needs-human: Build the widget")

    def test_credentials_are_removed_from_the_command_s_environment(self):
        self.record_calls()
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "secret"}):
            self.notify("needs-human")
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", self.calls()[0])


class NotifyFailureTest(NotifyCase):
    def test_a_missing_program_is_a_note(self):
        self.use("/nonexistent/notify-me")
        self.assertIn("NOTE: notify: can't run /nonexistent/notify-me", self.notify("needs-human"))

    def test_a_failing_command_is_a_note_with_its_last_stderr_line(self):
        self.use(sys.executable, "-c", "import sys; sys.stderr.write('first\\nboom\\n'); sys.exit(3)")
        self.assertEqual(self.notify("needs-human").strip(), f"NOTE: notify: {sys.executable} exited 3: boom")

    def test_a_hanging_command_times_out_as_a_note(self):
        self.use(sys.executable, "-c", "import time; time.sleep(10)")
        with mock.patch.object(self.job, "NOTIFY_TIMEOUT", 0.5):
            out = self.notify("needs-human")
        self.assertEqual(out.strip(), f"NOTE: notify: {sys.executable} timed out after 0.5s")


class NotifyCallSitesTest(NotifyCase):
    def test_stop_for_human_notifies_once(self):
        self.record_calls()
        with contextlib.redirect_stdout(io.StringIO()):
            self.job.stop_for_human(self.job.load(self.job_id), "the merge failed")
        [env] = self.calls()
        self.assertEqual(env["FACTORY_NOTIFY_STAGE"], "needs-human")
        self.assertIn("the merge failed", env["FACTORY_NOTIFY_MESSAGE"])
        self.assertEqual(self.job.load(self.job_id)["stage"], "needs-human")

    def test_a_failing_notify_still_moves_the_job(self):
        self.use("/nonexistent/notify-me")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.stop_for_human(self.job.load(self.job_id), "the merge failed")
        self.assertIn("NOTE: notify: can't run /nonexistent/notify-me", out.getvalue())
        self.assertEqual(self.job.load(self.job_id)["stage"], "needs-human")

    def test_needs_info_notifies_once(self):
        (self.d / "intake.md").write_text("DECISION: NEEDS-INFO\n\n## Questions\n1. Which page size?\n")
        self.record_calls()
        with contextlib.redirect_stdout(io.StringIO()):
            self.job.advance(self.job.load(self.job_id), "needs-info")
        [env] = self.calls()
        self.assertEqual(env["FACTORY_NOTIFY_STAGE"], "needs-info")
        self.assertIn("1. Which page size?", env["FACTORY_NOTIFY_MESSAGE"])


if __name__ == "__main__":
    unittest.main()
