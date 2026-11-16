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


if __name__ == "__main__":
    unittest.main()
