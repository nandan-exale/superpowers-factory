import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from factory_project import FactoryProject


class DigestTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        self.job.CONFIG["digest"] = {"enabled": True, "hour": 0, "days": 1}
        self.issues = []
        self.calls = []
        self.fail_on = None

        def fake_gh(*args):
            self.calls.append(args)
            if self.fail_on and args[:2] == self.fail_on:
                raise self.job.Refused("gh: boom")
            if args[:2] == ("issue", "list"):
                return json.dumps(self.issues)
            if args[:2] == ("issue", "create"):
                return "https://github.com/o/r/issues/31\n"
            return ""

        self.job.gh = fake_gh

    def digest(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_digest()
        return out.getvalue()

    def state(self):
        path = self.job.JOBS / "digest.json"
        return json.loads(path.read_text()) if path.exists() else None

    def test_creates_labels_and_pins_a_new_digest_issue(self):
        out = self.digest()
        self.assertIn("DIGEST: posted on #31", out)
        kinds = [c[:2] for c in self.calls]
        self.assertIn(("label", "create"), kinds)
        self.assertIn(("issue", "pin"), kinds)
        body = next(c for c in self.calls if c[:2] == ("issue", "comment"))
        self.assertEqual(body[2], "31")
        self.assertIn("Needs you: nothing", body[body.index("--body") + 1])
        self.assertEqual(self.state()["issue"], 31)

    def test_reuses_an_open_issue_and_reopens_a_closed_one(self):
        self.issues = [{"number": 5, "state": "CLOSED"}, {"number": 8, "state": "OPEN"}]
        self.digest()
        self.assertNotIn(("issue", "create"), [c[:2] for c in self.calls])
        self.assertEqual(next(c for c in self.calls if c[:2] == ("issue", "comment"))[2], "8")
        (self.job.JOBS / "digest.json").unlink()
        self.calls.clear()
        self.issues = [{"number": 5, "state": "CLOSED"}]
        self.digest()
        self.assertIn(("issue", "reopen", "5"), self.calls)

    def test_waits_for_the_hour_and_twenty_hours(self):
        self.job.CONFIG["digest"]["hour"] = 24  # never reached
        self.assertIn("DIGEST: not yet", self.digest())
        self.job.CONFIG["digest"]["hour"] = 0
        self.job.JOBS.mkdir(parents=True, exist_ok=True)
        recent = (datetime.now(timezone.utc) - timedelta(hours=19)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (self.job.JOBS / "digest.json").write_text(json.dumps({"posted": recent, "issue": 3}))
        self.assertIn("DIGEST: already posted", self.digest())
        self.assertEqual(self.calls, [])

    def test_off_when_disabled_and_defaults_when_missing(self):
        self.job.CONFIG["digest"]["enabled"] = False
        self.assertIn("DIGEST: off", self.digest())
        del self.job.CONFIG["digest"]
        self.assertEqual(self.job.digest_config(), {"enabled": True, "hour": 9, "days": 1})

    def test_gh_failure_is_a_note_and_records_nothing(self):
        self.fail_on = ("issue", "comment")
        out = self.digest()
        self.assertIn("NOTE: digest not posted", out)
        self.assertIsNone(self.state())

    def test_the_line_lists_waiting_jobs(self):
        d = self.job.JOBS / "012-x"
        d.mkdir(parents=True)
        ended = (datetime.now(timezone.utc) - timedelta(hours=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (d / "job.json").write_text(json.dumps({"id": "012-x", "issue": 12, "stage": "needs-human", "round": 1,
                                                "pr": 4, "cost_usd": 0, "started": ended, "ended": ended}))
        self.assertEqual(self.job.needs_you_line(self.job.report_data(1)), "Needs you: #12 (needs-human, 2d)")
