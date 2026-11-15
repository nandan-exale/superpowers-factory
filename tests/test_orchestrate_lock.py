import contextlib
import fcntl
import io
import os
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from script_loader import load_script

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"
ORCHESTRATE = PLUGIN / "vendor" / "factory" / "factory" / "bin" / "orchestrate"
BUSY_LINE = "orchestrate: another factory run is active in this clone\n"
CONFIG = {"base_branch": "main", "runtime": "codex", "runtimes": {"codex": {"credential_env": "OPENAI_API_KEY"}}}
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=GIT_ENV)


class OrchestrateLockTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name).resolve() / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "init")
        self.lock_path = self.repo / ".git" / "factory-orchestrate.lock"

        self.orch = load_script(ORCHESTRATE, "orchestrate_lock_under_test")
        self.runs = []
        self.constructed = []
        test = self

        class FakeLoop:
            def __init__(self, cli, pipeline, runtime, say=print, agent_env=None):
                test.constructed.append(self)

            def run(self, issue):
                test.runs.append(issue)
                with open(test.lock_path, "w") as other:
                    try:
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        test.locked_during_run = True
                    else:
                        test.locked_during_run = False
                return 0

            def stop(self):
                pass

        cli = types.SimpleNamespace(repo=self.repo, config=lambda: CONFIG)
        runtime = types.SimpleNamespace(NAME="codex", BINARY="true", CAPS={"stop_hook": False})
        for target, name, value in ((self.orch, "REPO", self.repo), (self.orch, "Loop", FakeLoop),
                                    (self.orch, "JobCli", lambda repo: cli),
                                    (self.orch.runtimes, "load", lambda name: runtime)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(signal.signal, signal.SIGTERM, signal.getsignal(signal.SIGTERM))
        self.locked_during_run = None

    def hold(self):
        lock = open(self.lock_path, "w")
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)

    def main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.orch.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_second_run_is_refused_while_the_lock_is_held(self):
        self.hold()
        code, out, err = self.main(["run"])
        self.assertEqual(code, 75)
        self.assertEqual(out, "")
        self.assertEqual(err, BUSY_LINE)
        self.assertEqual(self.constructed, [])
        self.assertEqual(self.runs, [])

    def test_run_n_is_refused_too(self):
        self.hold()
        self.assertEqual(self.main(["run", "7"])[0], 75)
        self.assertEqual(self.runs, [])

    def test_runs_and_holds_the_lock_while_the_loop_runs(self):
        for argv, issue in ((["run"], None), (["run", "7"], 7)):
            self.locked_during_run = None
            self.assertEqual(self.main(argv)[0], 0)
            self.assertEqual(self.runs[-1], issue)
            self.assertTrue(self.locked_during_run)

    def test_bad_usage_returns_2_even_while_the_lock_is_held(self):
        self.hold()
        for argv in ([], ["run", "x"], ["run", "1", "2"], ["stop"]):
            code, out, err = self.main(argv)
            self.assertEqual(code, 2, argv)
            self.assertNotEqual(err, BUSY_LINE)

    def test_lock_is_shared_by_a_linked_worktree(self):
        linked = self.repo.parent / "linked"
        git(self.repo, "worktree", "add", "-q", str(linked), "-b", "other")
        with mock.patch.object(self.orch, "REPO", linked):
            self.assertEqual(self.orch.lock_path().resolve(), self.lock_path)
        self.hold()
        with mock.patch.object(self.orch, "REPO", linked):
            self.assertEqual(self.main(["run"])[0], 75)

    def test_lock_is_released_when_the_holder_is_killed(self):
        holder = subprocess.Popen(
            [sys.executable, "-c", "import fcntl, sys\nf = open(sys.argv[1], 'w')\nfcntl.flock(f, fcntl.LOCK_EX)\n"
             "print('locked', flush=True)\nsys.stdin.read()", str(self.lock_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.stdin.close)
        self.addCleanup(holder.wait)
        self.assertEqual(holder.stdout.readline().strip(), "locked")
        self.assertEqual(self.main(["run"])[0], 75)
        holder.kill()
        holder.wait()
        self.assertEqual(self.main(["run"])[0], 0)

    def test_unreadable_git_dir_is_reported_not_raised(self):
        with mock.patch.object(self.orch, "REPO", self.repo.parent):  # not a git checkout
            code, out, err = self.main(["run"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("orchestrate: can't open the run lock:", err)
        self.assertEqual(self.constructed, [])


if __name__ == "__main__":
    unittest.main()
