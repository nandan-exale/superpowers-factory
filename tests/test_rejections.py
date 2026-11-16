import contextlib
import io
import tempfile
import unittest

from factory_project import FactoryProject

MARKER = "<!-- factory -->"
ADD_REJECTED = ("issue", "edit", "7", "--add-label", "factory:rejected")


def factory_comment(body, who="operator"):
    return {"author": {"login": who}, "body": f"{MARKER}\n{body}", "createdAt": "2026-11-01T00:00:00Z"}


def rejected_issue(number, comments, title="Add a spinner"):
    return {"number": number, "title": title, "url": f"https://github.com/o/r/issues/{number}",
            "comments": comments}


class RejectionTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = FactoryProject(self.tmp.name)
        self.project.set_issue("Add a spinner.", labels=("factory",))
        self.job = self.project.load_job()

    def tearDown(self):
        self.tmp.cleanup()

    def create(self):
        self.job_id = self.project.create_job(self.job)
        self.d = self.job.job_dir(self.job_id)

    def load(self):
        return self.job.sync(self.job.load(self.job_id))

    def decide(self, decision):
        (self.d / "intake.md").write_text(
            f"DECISION: {decision}\nRISK: low\nSURFACES: none\nRESCOPED: no\n\n"
            "## Summary\n- test\n\n## Why\nBecause.\n\n## Questions\n1. Which one?\n")

    def move(self, stage):
        self.job.save(self.job.advance(self.load(), stage))


class ConfigTest(RejectionTestCase):
    def test_rejected_label_configured(self):
        self.assertEqual(self.job.LABELS["rejected"], "factory:rejected")

    def test_scope_creep_is_a_learning_tag(self):
        self.assertIn("scope-creep", self.job.learning_config()["tags"])


class RecordTest(RejectionTestCase):
    def setUp(self):
        super().setUp()
        self.create()

    def test_intake_reject_adds_rejected_label(self):
        self.decide("REJECT")
        self.move("rejected")
        self.assertEqual(self.load()["stage"], "rejected")
        self.assertIn(("issue", "edit", "7", "--remove-label", "factory"), self.project.gh_calls)
        self.assertIn(ADD_REJECTED, self.project.gh_calls)

    def test_human_reject_from_needs_info_adds_rejected_label(self):
        self.decide("NEEDS-INFO")
        self.move("needs-info")
        with contextlib.redirect_stdout(io.StringIO()):
            self.job.cmd_reject(self.load(), "not for this project")
        self.assertEqual(self.load()["stage"], "rejected")
        self.assertIn(ADD_REJECTED, self.project.gh_calls)

    def test_missing_label_keeps_rejection_and_warns(self):
        def gh(*args):
            if "factory:rejected" in args:
                raise self.job.Refused("could not add label: 'factory:rejected' not found")
            self.project.gh_calls.append(args)
            return ""
        self.job.gh = gh
        self.decide("REJECT")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.move("rejected")
        self.assertEqual(self.load()["stage"], "rejected")
        self.assertIn("factory:rejected not added to #7", err.getvalue())


if __name__ == "__main__":
    unittest.main()
