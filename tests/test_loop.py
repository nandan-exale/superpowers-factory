import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "vendor" / "factory" / "factory" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator import loop as loop_mod  # noqa: E402
from orchestrator.jobcli import Out  # noqa: E402
from orchestrator.pipeline import Spawn  # noqa: E402
from test_pipeline import FakeCli  # noqa: E402

AGENT = """import json, os, sys, time
prompt = sys.stdin.read()
role = os.environ["FAKE_ROLE"]
own = os.environ.get("FAKE_OWN")
if own:
    os.makedirs(os.path.dirname(own), exist_ok=True)
    open(own, "w").write("VERDICT: PASS\\n")
stray = os.environ.get("FAKE_STRAY")
if stray:
    open(stray, "w").write("x")
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
code = int(os.environ.get("FAKE_EXIT_" + role.replace("-", "_"), "0"))
if code:
    sys.exit(code)
print(json.dumps({"session_id": "sess-" + role, "cost": 0.5, "resumed": "--resume" in sys.argv}))
"""


def fake_runtime(script, own_for, env):
    """own_for: {role: file relative to the job folder the fake agent writes}; env: extra FAKE_* settings."""
    def build(run):
        folder = run["repo"] / "factory" / "jobs" / run["job_id"]
        own = str(folder / own_for[run["role"]]) if run["role"] in own_for else ""
        return ([sys.executable, str(script)] + (["--resume", run["resume"]] if run["resume"] else []),
                {"FAKE_ROLE": run["role"], "FAKE_OWN": own, **env})

    def parse(stdout):
        data = json.loads(stdout)
        return {"session_id": data["session_id"], "model": "m", "usage": None, "cost_usd": data["cost"],
                "cost_source": "cli", "cost_by_model": {"m": data["cost"]}, "error": False}

    return types.SimpleNamespace(NAME="fake", build=build, parse=parse)


class FakePipeline:
    def __init__(self, first):
        self.first, self.daily, self.learn_files, self.finished = first, False, [], []

    def begin(self, row):
        return row[2], self.first.pop(row[2], [])

    def after(self, job_id, dones):
        self.finished.append((job_id, dones))
        return []

    def learn(self):
        return []


class LoopCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        agents = self.repo / "factory" / "agents"
        agents.mkdir(parents=True)
        for role, access in (("builder", "write"), ("reviewer-code", "read"), ("reviewer-ux", "read")):
            (agents / f"{role}.md").write_text(f"---\nname: {role}\naccess: {access}\n---\nBody of {role}.\n")
        self.script = self.repo / "agent.py"
        self.script.write_text(AGENT)
        self.folder = self.repo / "factory" / "jobs" / "004-x"
        self.folder.mkdir(parents=True)
        self.tree = self.repo / "wt"
        self.tree.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.tree, check=True)
        self.cli = FakeCli(self.repo)
        self.cli.answer("job", "queue", out="resume\t12\t004-x\tbuild\tround 1\n")
        self.cli.answer("job", "watch", out="WATCH: off\n")
        self.lines = []
        self.env = {}

    def spawn(self, role, own=(), **kw):
        return Spawn("004-x", role, "PROMPT", self.tree, self.folder, own, "m", "high", **kw)

    own_for = {}

    def loop(self, spawns):
        self.pipe = FakePipeline({"004-x": spawns})
        rt = fake_runtime(self.script, self.own_for, self.env)
        return loop_mod.Loop(self.cli, self.pipe, rt, say=self.lines.append, poll=0.05)

    def recorded(self):
        return [json.loads(stdin) for args, stdin in self.cli.calls if args[:2] == ("job", "record-run")]


class LoopTest(LoopCase):
    def test_runs_a_batch_records_it_and_hands_it_to_the_pipeline(self):
        self.own_for = {"reviewer-code": "round-1/review-code.md", "reviewer-ux": "round-1/review-ux.md"}
        lp = self.loop([self.spawn("reviewer-code", ("round-1/review-code.md",)),
                        self.spawn("reviewer-ux", ("round-1/review-ux.md",))])
        self.assertEqual(lp.run(), 0)
        (job_id, dones), = self.pipe.finished
        self.assertEqual([d.ok for d in dones], [True, True])
        self.assertEqual([d.session_id for d in dones], ["sess-reviewer-code", "sess-reviewer-ux"])
        runs = self.recorded()
        self.assertEqual(sorted(r["role"] for r in runs), ["reviewer-code", "reviewer-ux"])
        self.assertEqual({r["cost_usd"] for r in runs}, {0.5})
        self.assertIn("SPENT: $1.00", self.lines)
        self.assertEqual(len(self.cli.called("job", "sync", "004-x")), 2)
        prompt_files = list((self.folder / "runs").glob("*-reviewer-code.prompt.md"))
        self.assertEqual(prompt_files[0].read_text(), "PROMPT")

    def test_a_failing_agent_is_retried_once_then_reported(self):
        self.env = {"FAKE_EXIT_builder": "1"}
        lp = self.loop([self.spawn("builder")])
        lp.run()
        (_, (done,)), = self.pipe.finished
        self.assertFalse(done.ok)
        self.assertIn("twice", done.note)
        self.assertEqual(len(self.recorded()), 2)

    def test_failed_resume_falls_back_to_a_fresh_agent(self):
        self.env = {"FAKE_EXIT_builder": "1"}
        lp = self.loop([self.spawn("builder", resume="old", fresh_prompt="FRESH")])
        lp.run()
        self.assertEqual(len(self.recorded()), 3)   # resume, then a fresh agent twice
        prompts = sorted(p.read_text() for p in (self.folder / "runs").glob("*-builder.prompt.md"))
        self.assertIn("FRESH", prompts)

    def test_read_only_violation_fails_the_batch_and_quarantines(self):
        self.own_for = {"reviewer-code": "round-1/review-code.md"}
        self.env = {"FAKE_STRAY": str(self.folder / "spec.md")}
        lp = self.loop([self.spawn("reviewer-code", ("round-1/review-code.md",))])
        lp.run()
        (_, (done,)), = self.pipe.finished
        self.assertFalse(done.ok)
        self.assertIn("wrote files it doesn't own: spec.md", done.note)
        self.assertTrue((self.folder / "runs" / "round-1--review-code.md.rejected").exists())

    def test_paused_queue_starts_nothing(self):
        self.cli.answer("job", "queue", out="PAUSED: main is red (since t; …)\nwait\t12\t004-x\tbuild\tpaused\n")
        lp = self.loop([self.spawn("builder")])
        lp.run()
        self.assertEqual(self.pipe.finished, [])
        self.assertIn("PAUSED: main is red (since t; …)", self.lines)

    def test_run_one_issue_ignores_others(self):
        lp = self.loop([self.spawn("builder")])
        lp.run(only=99)
        self.assertEqual(self.pipe.finished, [])

    def test_stop_kills_running_agents(self):
        self.env = {"FAKE_SLEEP": "30"}
        lp = self.loop([self.spawn("builder")])
        lp.fill(None)
        procs = [r["proc"] for b in lp.batches.values() for r in b["runs"].values()]
        lp.stop()
        for p in procs:
            self.assertIsNotNone(p.wait(timeout=5))


class OrchestrateScriptTest(unittest.TestCase):
    def test_usage_on_bad_arguments(self):
        script = PLUGIN / "vendor" / "factory" / "factory" / "bin" / "orchestrate"
        res = subprocess.run([sys.executable, str(script), "nonsense"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("orchestrate run", res.stderr)
        self.assertTrue(os.access(script, os.X_OK))

    def test_leaves_no_bytecode_in_the_project(self):
        """The runner skips a dirty tree, so importing factory/lib must not write __pycache__ there."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vendor = PLUGIN / "vendor" / "factory" / "factory"
            (root / "factory" / "bin").mkdir(parents=True)
            shutil.copy2(vendor / "bin" / "orchestrate", root / "factory" / "bin" / "orchestrate")
            shutil.copytree(vendor / "lib", root / "factory" / "lib",
                            ignore=shutil.ignore_patterns("__pycache__"))
            res = subprocess.run([sys.executable, str(root / "factory" / "bin" / "orchestrate"), "nonsense"],
                                 capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": ""})
            self.assertEqual(res.returncode, 2, res.stderr)
            self.assertEqual(list(root.rglob("__pycache__")), [])


if __name__ == "__main__":
    unittest.main()
