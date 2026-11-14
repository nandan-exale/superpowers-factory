import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "vendor" / "factory" / "factory" / "lib"))

from orchestrator import agents, jobcli, prompts  # noqa: E402

REPO = Path("/r")
JOB = {"id": "004-dark-mode", "worktree": "/r/.worktrees/004-dark-mode", "branch": "factory/004-dark-mode",
       "issue": 12, "round": 2, "pr": 30}


class AgentsTest(unittest.TestCase):
    def test_every_vendored_agent_loads(self):
        repo = PLUGIN / "vendor" / "factory"
        for role in ("intake", "spec-writer", "builder", "approver", "learner",
                     "reviewer-code", "reviewer-security", "reviewer-ux", "reviewer-ui"):
            a = agents.load(repo, role)
            self.assertIn(a["access"], ("read", "write"), role)
            self.assertFalse(a["body"].startswith("---"), role)
        self.assertEqual(agents.load(repo, "builder")["access"], "write")
        self.assertEqual(agents.load(repo, "reviewer-code")["access"], "read")

    def test_bad_access_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "factory" / "agents"
            d.mkdir(parents=True)
            (d / "x.md").write_text("---\nname: x\naccess: maybe\n---\nbody\n")
            with self.assertRaisesRegex(ValueError, "access must be read or write"):
                agents.load(Path(tmp), "x")


class PromptsTest(unittest.TestCase):
    def test_header_is_the_skill_header(self):
        self.assertEqual(prompts.header(REPO, JOB, "main"),
                         "Job: 004-dark-mode. Job folder: /r/factory/jobs/004-dark-mode/. Main checkout: /r. "
                         "Worktree: /r/.worktrees/004-dark-mode. Branch: factory/004-dark-mode. "
                         "Base: origin/main. Issue: #12.")

    def test_header_without_worktree_and_with_tasks(self):
        line = prompts.header(REPO, {**JOB, "tasks": "4-7", "plan_tasks": 12}, "main", worktree=False)
        self.assertIn("Worktree: none, it doesn't exist yet. Work in the main checkout.", line)
        self.assertTrue(line.endswith("Issue: #12. Tasks: 4-7 of 12."))

    def test_ports(self):
        cfg = {"ports": {"base": 5100, "step": 10}}
        self.assertEqual(prompts.port(cfg, "004-dark-mode", "builder"), 5140)
        self.assertEqual(prompts.port(cfg, "004-dark-mode", "reviewer-ux"), 5141)
        self.assertEqual(prompts.port(cfg, "004-dark-mode", "reviewer-ui"), 5142)
        self.assertIsNone(prompts.port(cfg, "004-dark-mode", "reviewer-code"))

    def test_step_texts(self):
        self.assertEqual(prompts.build("H", 2, 5140, "Fix it."), "H Build round 2. Port: 5140. Fix it.")
        self.assertEqual(prompts.build("H", 1, 5140), "H Build round 1. Port: 5140.")
        self.assertEqual(prompts.review("H", 2, None), "H Review round 2.")
        self.assertEqual(prompts.review("H", 2, 5141), "H Review round 2. Port: 5141.")
        self.assertEqual(prompts.approve("H", 30, 2), "H PR: #30. Final round: 2.")
        self.assertEqual(prompts.gate_failed(1),
                         "The gate failed: read round-1/checks.md and checks.log, fix it, push, and update build.md.")
        self.assertEqual(prompts.changes(1, 2), "Round 1 reviews are in round-1/. Address every VERDICT: CHANGES, "
                                                "push, and update build.md for round 2.")
        self.assertEqual(prompts.learner(REPO, "missing-test", "missing-test"),
                         "Job folder: /r/factory/jobs/learning/missing-test/. missing-test")


class JobCliTest(unittest.TestCase):
    def test_runs_scripts_with_stdin_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "factory" / "bin").mkdir(parents=True)
            (repo / "factory" / "bin" / "job").write_text(
                "import sys\ndata = sys.stdin.read()\nprint('args', *sys.argv[1:], data)\n"
                "sys.exit(3 if 'bad' in sys.argv else 0)\n")
            cli = jobcli.JobCli(repo)
            out = cli.job("advance", "001-x", "spec", stdin="hi")
            self.assertTrue(out.ok)
            self.assertEqual(out.out.strip(), "args advance 001-x spec hi")
            self.assertFalse(cli.job("bad").ok)
            self.assertEqual(cli.job("bad").code, 3)

    def test_scripts_never_read_the_orchestrator_s_stdin(self):
        # A `job` call without input must not wait on (or read) the terminal orchestrate runs in.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "factory" / "bin").mkdir(parents=True)
            (repo / "factory" / "bin" / "job").write_text("import sys\nprint(repr(sys.stdin.read()))\n")
            code = ("import sys; sys.path.insert(0, sys.argv[1]); from orchestrator import jobcli; "
                    "print(jobcli.JobCli(sys.argv[2]).job('queue').out, end='')")
            lib = str(PLUGIN / "vendor" / "factory" / "factory" / "lib")
            proc = subprocess.Popen([sys.executable, "-c", code, lib, tmp], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, text=True)
            self.addCleanup(proc.stdin.close)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                self.fail("job waited on the orchestrator's stdin")
            self.assertEqual(proc.stdout.read().strip(), "''")
            proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
