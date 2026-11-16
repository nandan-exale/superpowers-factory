import contextlib
import fcntl
import io
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from factory_project import FactoryProject

TIMEOUT = 30

FAKE_GH = """#!/bin/sh
case "$1 $2" in
  "issue view") printf '{"number": %s, "title": "Build the widget", "body": "", "author": {"login": "operator"}, "labels": [], "state": "OPEN", "url": "https://github.com/o/r/issues/%s", "comments": []}' "$3" "$3" ;;
  "issue list") echo '[]' ;;
  "api user") echo operator ;;
esac
"""

# Runs bin/job. With LOCK_BARRIER set, the process stops right after its first flock until two processes
# hold one, so two commands are sure to overlap: each holds its own lock before either reads the other jobs.
DRIVER = """
import fcntl, os, runpy, sys, time

barrier = os.environ.get("LOCK_BARRIER")
real_flock = fcntl.flock
first = []

def flock(fd, op):
    real_flock(fd, op)
    if barrier and not first:
        first.append(True)
        open(os.path.join(barrier, str(os.getpid())), "w").close()
        deadline = time.time() + 5
        while len(os.listdir(barrier)) < 2 and time.time() < deadline:
            time.sleep(0.02)

fcntl.flock = flock
job = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(job, run_name="__main__")
"""


class JobLocksTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.project = FactoryProject(self.tmp)
        self.job = self.project.load_job()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        (self.tmp / "driver.py").write_text(DRIVER)
        (self.tmp / "barrier").mkdir()
        self.script = self.project.repo / "factory" / "bin" / "job"
        self.next_issue = 7

    def make_job(self, stage, **fields):
        number, self.next_issue = self.next_issue, self.next_issue + 1
        self.project.set_issue("Build the widget.", labels=("factory",), number=number)
        job_id = self.project.create_job(self.job)
        # Created in this process, which must not keep the slot lock the subprocesses need.
        self.job._slot_lock.close()
        self.job._slot_lock = None
        job = {**self.job.load(job_id), "stage": stage, **fields}
        self.job.save(job)
        if stage == "needs-info":
            (self.job.job_dir(job_id) / "intake.md").write_text("DECISION: NEEDS-INFO\n")
        return job_id

    def start(self, *args, barrier=False):
        env = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}
        if barrier:
            env["LOCK_BARRIER"] = str(self.tmp / "barrier")
        return subprocess.Popen([sys.executable, str(self.tmp / "driver.py"), str(self.script), *args],
                                cwd=self.project.repo, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    def finish(self, *procs):
        """(returncode, stdout, stderr) of each process; a process still running at the timeout fails the test."""
        results = []
        for proc in procs:
            try:
                out, err = proc.communicate(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                for p in procs:
                    p.kill()
                    p.communicate()
                self.fail(f"{proc.args[3:]} still running after {TIMEOUT}s: blocked on a lock")
            results.append((proc.returncode, out, err))
        return results

    def stage(self, job_id):
        return self.job.load(job_id)["stage"]

    def test_advancing_two_jobs_at_once_doesnt_deadlock(self):
        a, b = self.make_job("needs-info"), self.make_job("needs-info")
        results = self.finish(self.start("advance", a, "intake", barrier=True),
                              self.start("advance", b, "intake", barrier=True))
        self.assertEqual([r[0] for r in results], [0, 0], results)
        self.assertEqual((self.stage(a), self.stage(b)), ("intake", "intake"))

    def test_summary_isnt_blocked_by_held_locks(self):
        a, b = self.make_job("build"), self.make_job("review")
        held = [open(self.job.job_dir(j) / ".lock", "w") for j in (a, b)]
        held.append(open(self.job.JOBS / ".slots.lock", "w"))
        for f in held:
            self.addCleanup(f.close)
            fcntl.flock(f, fcntl.LOCK_EX)
        [(code, out, err)] = self.finish(self.start("summary"))
        self.assertEqual(code, 0, err)
        self.assertIn(a, out)
        self.assertIn(b, out)

    def test_concurrency_limit_holds_under_concurrent_advance(self):
        for _ in range(self.job.CONCURRENCY - 1):
            self.make_job("build")
        a, b = self.make_job("needs-info"), self.make_job("needs-info")
        results = self.finish(self.start("advance", a, "intake", barrier=True),
                              self.start("advance", b, "intake", barrier=True))
        self.assertEqual(sorted(r[0] for r in results), [0, 1], results)
        refused = next(r for r in results if r[0] != 0)
        self.assertRegex(refused[2], f"concurrency {self.job.CONCURRENCY} reached")
        self.assertEqual(sorted([self.stage(a), self.stage(b)]), ["intake", "needs-info"])
        [(code, out, err)] = self.finish(self.start("summary"))
        self.assertEqual(code, 0, err)
        self.assertEqual(sum(1 for line in out.splitlines() if " intake " in line), 1, out)

    def test_a_waiting_process_sees_what_the_holder_saved(self):
        a = self.make_job("needs-info")
        results = self.finish(self.start("advance", a, "intake"), self.start("advance", a, "intake"))
        self.assertEqual(sorted(r[0] for r in results), [0, 1], results)
        refused = next(r for r in results if r[0] != 0)
        self.assertIn("intake → intake is not a legal transition", refused[2])

    def test_a_second_job_lock_is_refused_not_waited_for(self):
        a, b = self.make_job("build"), self.make_job("build")
        self.job.lock_job(a)
        self.assertEqual(self.job.lock_job(a)["id"], a)  # the same job again is no new lock
        signal.signal(signal.SIGALRM, lambda *_: self.fail("lock_job waited instead of failing"))
        signal.alarm(10)
        self.addCleanup(signal.alarm, 0)
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            self.job.lock_job(b)
        self.assertIn(f"asked for job {b}'s lock while holding {a}", err.getvalue())

    def test_queue_holds_no_job_lock_after_merging_several(self):
        ids = [self.make_job("review", pr=n) for n in (31, 32, 33)]
        self.job.pr_state = lambda job: "MERGED"
        self.job.gh_json = lambda *args: []
        with contextlib.redirect_stdout(io.StringIO()):
            self.job.cmd_queue()
        self.assertEqual(self.job.__dict__["_locks"], {})
        self.assertEqual([self.stage(j) for j in ids], ["merged"] * 3)
        for j in ids:
            with open(self.job.job_dir(j) / ".lock", "w") as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)


if __name__ == "__main__":
    unittest.main()
