import importlib.machinery
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import FactoryProject  # noqa: E402


class FakeSubprocess:
    """Stands in for job's `subprocess`: returns the queued exit codes, or raises on "timeout"."""
    TimeoutExpired = subprocess.TimeoutExpired
    CompletedProcess = subprocess.CompletedProcess

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def run(self, cmd, **kw):
        self.calls.append((cmd, kw))
        outcome = self.outcomes.pop(0)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        return subprocess.CompletedProcess(cmd, outcome, "", "boom" if outcome else "")


class RetryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        path = self.project.repo / "factory" / "bin" / "job"
        loader = importlib.machinery.SourceFileLoader(f"job_raw_{id(self)}", str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.job = importlib.util.module_from_spec(spec)
        loader.exec_module(self.job)  # real gh/git helpers, unlike load_job()
        self.job.NET_WAITS = (0, 0, 0)

    def fake(self, *outcomes):
        fake = FakeSubprocess(*outcomes)
        self.job.subprocess = fake
        return fake

    def test_a_failed_fetch_is_retried(self):
        fake = self.fake(1, 0)
        self.job.run_net(["git", "fetch", "origin", "main"])
        self.assertEqual(len(fake.calls), 2)
        self.assertTrue(all(kw.get("timeout") == self.job.NET_TIMEOUT for _, kw in fake.calls))

    def test_three_failures_refuse(self):
        fake = self.fake(1, 1, 1)
        with self.assertRaises(self.job.Refused):
            self.job.run_net(["git", "fetch", "origin", "main"])
        self.assertEqual(len(fake.calls), 3)

    def test_a_timeout_counts_as_a_failure(self):
        fake = self.fake("timeout", "timeout", 0)
        self.job.run_net(["git", "fetch", "origin", "main"])
        self.assertEqual(len(fake.calls), 3)

    def test_unchecked_failure_returns_the_last_result(self):
        self.fake(1, 1, 1)
        self.assertEqual(self.job.run_net(["git", "fetch"], check=False).returncode, 1)

    def test_read_only_gh_is_retried(self):
        fake = self.fake(1, 0)
        self.job.gh("pr", "view", "1", "--json", "state")
        self.assertEqual(len(fake.calls), 2)

    def test_gh_api_get_is_retried(self):
        fake = self.fake(1, 0)
        self.job.gh("api", "--paginate", "--jq", ".[]", "repos/o/r/pulls/1/comments")
        self.assertEqual(len(fake.calls), 2)

    def test_gh_writes_run_once(self):
        for args in (("issue", "create", "--title", "x"), ("pr", "merge", "1", "--squash"),
                     ("api", "repos/o/r/issues", "-f", "title=x"), ("api", "-X", "DELETE", "x"),
                     ("api", "--method=POST", "x"), ("api", "x", "-ftitle=x"), ("api", "x", "-Fn=1"),
                     ("api", "-XPATCH", "x")):
            fake = self.fake(1)
            with self.assertRaises(self.job.Refused):
                self.job.gh(*args)
            self.assertEqual(len(fake.calls), 1, args)

    def test_job_git_fetch_and_push_are_retried(self):
        job = {"worktree": str(self.project.repo)}
        for verb in ("fetch", "push"):
            fake = self.fake(1, 0)
            self.job.git(job, verb, "origin", "main")
            self.assertEqual(len(fake.calls), 2, verb)

    def test_job_git_local_commands_run_once(self):
        fake = self.fake(1)
        self.job.git({"worktree": str(self.project.repo)}, "status", check=False)
        self.assertEqual(len(fake.calls), 1)


if __name__ == "__main__":
    unittest.main()
