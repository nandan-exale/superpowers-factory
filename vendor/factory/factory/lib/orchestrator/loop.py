"""Runs agents as child processes, at most `concurrency` jobs at a time (job queue decides), and hands
each finished batch to the pipeline."""

import json
import os
import signal
import subprocess
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone

from orchestrator import agents, readonly
from orchestrator.pipeline import Done, Stop

POLL_SECONDS = 0.5
LOG_TAIL = 40


def utc(fmt="%Y-%m-%dT%H:%M:%SZ"):
    return datetime.now(timezone.utc).strftime(fmt)


def kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass  # the group already exited


class Loop:
    def __init__(self, cli, pipeline, runtime, say=print, poll=POLL_SECONDS):
        self.cli, self.pipe, self.rt, self.say, self.poll = cli, pipeline, runtime, say, poll
        self.repo = cli.repo
        self.batches = {}        # key (job id, or learning:<tag>) → batch
        self.started = set()     # issues begun this run: a job that stops isn't restarted in the same run
        self.touched = []
        self.spent = 0.0
        self.paused = False
        self.stopping = False
        self.code = 0

    # ---- processes ---------------------------------------------------------------

    def launch(self, key, i, spawn):
        batch = self.batches[key]
        agent = agents.load(self.repo, spawn.role)
        runs = spawn.folder / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        stem = f"{utc('%Y%m%dT%H%M%S')}{time.time_ns() % 1_000_000:06d}-{spawn.role}"
        (runs / f"{stem}.system.md").write_text(agent["body"])
        (runs / f"{stem}.prompt.md").write_text(spawn.prompt)
        run = {"repo": self.repo, "job_id": spawn.job_id, "role": spawn.role, "access": agent["access"],
               "model": spawn.model, "effort": spawn.effort, "system_path": runs / f"{stem}.system.md",
               "settings_dir": runs, "stem": stem, "resume": spawn.resume,
               "session_id": None if spawn.resume else str(uuid.uuid4())}
        argv, env = self.rt.build(run)
        record = {"spawn": spawn, "stem": stem, "runs": runs, "started": utc(), "proc": None}
        try:
            with (runs / f"{stem}.prompt.md").open() as stdin, (runs / f"{stem}.out").open("w") as out, \
                    (runs / f"{stem}.log").open("w") as err:
                record["proc"] = subprocess.Popen(argv, cwd=spawn.cwd, env={**os.environ, **env}, stdin=stdin,
                                                  stdout=out, stderr=err, start_new_session=True)
        except OSError as exc:
            batch["done"][i] = Done(spawn, False, None, f"could not start {argv[0]}: {exc}")
            return
        batch["runs"][i] = record

    def finish(self, key, i, record, code):
        batch, spawn = self.batches[key], record["spawn"]
        text = (record["runs"] / f"{record['stem']}.out").read_text()
        try:
            parsed = self.rt.parse(text)
            problem = "an error result" if parsed["error"] else (f"exit {code}" if code else None)
        except ValueError as exc:
            parsed, problem = None, f"exit {code}, output unreadable ({exc})"
        self.record(spawn, record, code, parsed)
        if problem and spawn.resume:
            fresh = replace(spawn, resume=None, prompt=spawn.fresh_prompt or spawn.prompt, fresh_prompt=None)
            self.say(f"{spawn.job_id}: {spawn.role} couldn't resume ({problem}); starting a fresh one")
            batch["spawns"][i] = fresh
            self.launch(key, i, fresh)
            return
        if problem:
            batch["tries"][i] = batch["tries"].get(i, 0) + 1
            if batch["tries"][i] < 2:
                self.say(f"{spawn.job_id}: {spawn.role} failed ({problem}); trying once more")
                self.launch(key, i, spawn)
                return
            log = record["runs"] / f"{record['stem']}.log"
            tail = "\n".join(log.read_text(errors="replace").splitlines()[-LOG_TAIL:])
            batch["done"][i] = Done(spawn, False, None,
                                    f"failed twice ({problem}). Last lines of runs/{log.name}:\n\n```\n{tail}\n```")
            return
        batch["done"][i] = Done(spawn, True, parsed.get("session_id"))
        if spawn.role.startswith("reviewer-"):
            self.cli.job("sync", spawn.job_id)

    def record(self, spawn, record, code, parsed):
        p = parsed or {}
        data = {"role": spawn.role, "runtime": self.rt.NAME, "model": p.get("model") or spawn.model,
                "effort": spawn.effort, "session_id": p.get("session_id"), "started": record["started"],
                "ended": utc(), "exit": code, "usage": p.get("usage"), "cost_usd": p.get("cost_usd"),
                "cost_source": p.get("cost_source"), "cost_by_model": p.get("cost_by_model") or {},
                "log": f"runs/{record['stem']}.log"}
        out = self.cli.job("record-run", spawn.job_id, spawn.role, stdin=json.dumps(data))
        if not out.ok:
            self.say(f"{spawn.job_id}: record-run failed: {out.text}")
        self.spent += data["cost_usd"] or 0.0

    # ---- batches -----------------------------------------------------------------

    def start(self, key, spawns):
        first = spawns[0]
        read_only = all(agents.load(self.repo, s.role)["access"] == "read" for s in spawns)
        snap = readonly.snapshot(first.folder, first.cwd, first.cwd != self.repo) if read_only else None
        self.batches[key] = {"spawns": list(spawns), "runs": {}, "done": {}, "tries": {}, "snap": snap}
        for i, spawn in enumerate(spawns):
            self.launch(key, i, spawn)

    def settle(self, key):
        batch = self.batches.pop(key)
        dones = [batch["done"][i] for i in range(len(batch["spawns"]))]
        first = batch["spawns"][0]
        if batch["snap"] is not None and all(d.ok for d in dones):
            own = {f for s in batch["spawns"] for f in s.own}
            after = readonly.snapshot(first.folder, first.cwd, first.cwd != self.repo)
            problems = readonly.violations(batch["snap"], after, own)
            if problems:
                readonly.quarantine(first.folder, own)
                note = "broke the read-only rule: " + "; ".join(problems)
                dones = [Done(d.spawn, False, d.session_id, note) for d in dones]
        try:
            nxt = self.pipe.after(first.job_id, dones)
        except Stop as exc:
            self.say(f"{first.job_id}: stopped: {exc}")
            nxt = []
        if nxt:
            self.start(key, nxt)

    def reap(self):
        for key in list(self.batches):
            batch = self.batches[key]
            for i, record in list(batch["runs"].items()):
                code = record["proc"].poll()
                if code is None:
                    continue
                kill_group(record["proc"])  # on purpose: stops dev servers the agent left behind
                del batch["runs"][i]
                self.finish(key, i, record, code)
            if not batch["runs"] and len(batch["done"]) == len(batch["spawns"]):
                self.settle(key)
                if not key.startswith("learning:"):
                    self.fill(self.only)

    # ---- the queue -----------------------------------------------------------------

    only = None

    def fill(self, only):
        if self.stopping or self.pipe.daily:
            return
        out = self.cli.job("queue")
        if not out.ok:
            self.say(f"queue: {out.text}")
            self.code = 1
            return
        lines = out.out.splitlines()
        if lines and lines[0].startswith("PAUSED:"):
            if not self.paused:
                self.say(lines[0])
            self.paused = True
            return
        for line in lines:
            row = line.split("\t")
            if len(row) < 5:
                continue
            action, issue, job_id, note = row[0], row[1], row[2], row[4]
            if only is not None and issue != str(only):
                continue
            if action == "wait" and note.startswith("daily budget"):
                self.say(f"{note}: starting nothing else")
                self.pipe.daily = True
                return
            if action not in ("resume", "new") or issue in self.started or job_id in self.batches:
                continue
            self.started.add(issue)
            self.begin(row)

    def begin(self, row):
        try:
            job_id, spawns = self.pipe.begin(row)
        except Stop as exc:
            self.say(f"#{row[1]}: stopped: {exc}")
            return
        if job_id not in self.touched:
            self.touched.append(job_id)
        if spawns:
            self.start(job_id, spawns)

    # ---- the run -------------------------------------------------------------------

    def drain(self):
        while self.batches and not self.stopping:
            time.sleep(self.poll)
            self.reap()

    def run(self, only=None):
        self.only = only
        if only is None:
            for line in self.cli.job("watch").out.splitlines():
                if line.strip() and line.strip() != "WATCH: off":
                    self.say(line)
        self.fill(only)
        self.drain()
        if only is None and not (self.pipe.daily or self.paused or self.stopping or self.code):
            try:
                learners = self.pipe.learn()
            except Stop as exc:
                self.say(f"learn: {exc}")
                learners = []
            for spawn in learners:
                self.start(f"learning:{spawn.job_id}", [spawn])
            self.drain()
        self.wrap_up(only)
        return self.code

    def wrap_up(self, only):
        if self.touched:
            self.say(self.cli.job("summary", *self.touched).text)
        for line in self.pipe.learn_files:
            self.say(line)
        if only is None:
            self.cli.job("report", "--write")
            for line in self.cli.job("digest").out.splitlines():
                if line.startswith(("DIGEST:", "NOTE:")):
                    self.say(line)
        self.say(f"SPENT: ${self.spent:.2f}")

    def stop(self):
        self.stopping = True
        for batch in self.batches.values():
            for record in batch["runs"].values():
                kill_group(record["proc"])
