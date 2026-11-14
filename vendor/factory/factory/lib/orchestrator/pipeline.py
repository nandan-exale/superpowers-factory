"""What happens after each step of a job: the factory skill's pipeline, as code. State changes only
through factory/bin/job, gate and route; this module reads job.json and the agents' files."""

import re
from dataclasses import dataclass, replace
from pathlib import Path

from orchestrator import prompts


@dataclass(frozen=True)
class Spawn:
    job_id: str          # a learning tag for the learner
    role: str            # intake, spec-writer, builder, approver, reviewer-<r>, learner
    prompt: str
    cwd: Path
    folder: Path         # the job folder; the run's files go to its runs/
    own: tuple           # files, relative to folder, this run may write
    model: str = ""
    effort: str = ""
    resume: str | None = None
    fresh_prompt: str | None = None   # for a fresh agent when resuming fails


@dataclass(frozen=True)
class Done:
    spawn: Spawn
    ok: bool
    session_id: str | None = None
    note: str = ""


class Stop(Exception):
    """This job can't go on in this run; the message says why."""


class Refused(Stop):
    """A script refused a move; its message says why."""


def first_line(path):
    return path.read_text().split("\n", 1)[0].strip() if path.exists() else None


def header_field(path, key):
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if not line.strip():
            return None
        k, _, v = line.partition(":")
        if k.strip().upper() == key:
            return v.strip()
    return None


class Pipeline:
    def __init__(self, cli, say=print):
        self.cli, self.say = cli, say
        self.repo = cli.repo
        self.cfg = cli.config()
        self.base = self.cfg["base_branch"]
        self.retried = set()     # (job_id, role): already asked once to fix a refused result
        self.ready = set()       # jobs whose worktree this run has ensured
        self.daily = False       # the daily budget stopped this run
        self.learn_files = []

    # ---- helpers -------------------------------------------------------------

    def folder(self, job_id):
        return self.repo / "factory" / "jobs" / job_id

    def head(self, job, worktree=True):
        return prompts.header(self.repo, job, self.base, worktree)

    def run(self, *args, stdin=None):
        out = self.cli.job(*args, stdin=stdin)
        if not out.ok:
            raise Stop(out.text)
        return out.out

    def move(self, job_id, stage):
        """True when the job moved; False when a budget stopped it instead (finished for this run)."""
        out = self.cli.job("advance", job_id, stage)
        if out.ok and out.out.startswith("BUDGET:"):
            self.say(out.out.strip())
            return False
        if not out.ok:
            if "daily budget" in out.text:
                self.daily = True
                raise Stop(out.text)
            raise Refused(out.text)
        self.say(out.out.strip())
        return True

    def ensure(self, job_id):
        """The job's worktree exists (recreated on a fresh machine); False when the job went to needs-human."""
        if job_id in self.ready:
            return True
        out = self.run("ensure-worktree", job_id).strip()
        self.say(out)
        if not out.startswith("WORKTREE:"):
            return False
        self.ready.add(job_id)
        return True

    def make(self, job_id, role, prompt, cwd, own, resume=None, fresh_prompt=None, folder=None):
        out = self.run("agent", job_id, role).strip()
        m = re.fullmatch(r"model=(\S+) effort=(\S+)", out)
        if not m:
            raise Stop(f"job agent {job_id} {role} printed {out!r}")
        return Spawn(job_id, role, prompt, Path(cwd), folder or self.folder(job_id), tuple(own),
                     m.group(1), m.group(2), resume, fresh_prompt)

    def escalate(self, job_id, why):
        self.say(self.run("escalate", job_id, stdin=why).strip())
        return []

    def again(self, spawn, why):
        """Ask the agent once to fix a refused result (resuming the builder), then escalate."""
        key = (spawn.job_id, spawn.role)
        if key in self.retried:
            return self.escalate(spawn.job_id, f"{spawn.role}: {why}")
        self.retried.add(key)
        prompt = f"{spawn.prompt}\n\n{prompts.refused(why)}"
        if spawn.role == "builder":
            session = (self.cli.state(spawn.job_id).get("sessions") or {}).get("builder")
            if session:
                return [replace(spawn, prompt=prompts.refused(why), resume=session, fresh_prompt=prompt)]
        return [replace(spawn, prompt=prompt, resume=None, fresh_prompt=None)]

    def pr_feedback(self, job_id):
        line = self.run("pr-feedback", job_id).strip().splitlines()[-1:] or [""]
        text = line[0].removeprefix("PR-FEEDBACK:").strip()
        return [] if text in ("", "none") else text.split(" (", 1)[0].split()

    def next_round(self, job_id):
        """build for the next round; needs-human when it was the last. True when the builder runs again."""
        try:
            return self.move(job_id, "build")
        except Refused as e:
            if "go to needs-human" not in str(e):
                raise
        self.move(job_id, "needs-human")
        return False

    # ---- spawning each role ----------------------------------------------------

    def intake(self, job_id):
        job = self.cli.state(job_id)
        labels = self.cli.gh("issue", "view", job["issue"], "--json", "labels", "--jq", ".labels[].name")
        if not labels.ok:
            raise Stop(labels.text)
        if self.cfg["labels"]["planned"] in labels.out.split():
            out = self.cli.job("planned", job_id)
            line = next((l for l in out.out.splitlines() if l.startswith("PLANNED:")), None)
            if line is None:
                raise Stop(out.text)
            self.say(line)
            if "REFUSED" in line or not self.ensure(job_id):
                return []
            return self.builder(job_id)
        return [self.make(job_id, "intake", self.head(job, worktree=False), self.repo, ("intake.md",))]

    def spec_writer(self, job_id):
        job = self.cli.state(job_id)
        return [self.make(job_id, "spec-writer", self.head(job), job["worktree"], ("spec.md",))]

    def builder(self, job_id, why="", resuming=False):
        job = self.cli.state(job_id)
        n, port = job["round"], prompts.port(self.cfg, job_id, "builder")
        session = (job.get("sessions") or {}).get("builder")
        same_agent = prompts.build(self.head(job), n, port, why)
        # A fresh builder after round 1, or on a resume, must first find out how far the last one got.
        fresh = prompts.build(self.head(job), n, port, " ".join(w for w in (why, prompts.RESUMING) if w)) \
            if resuming or n > 1 else same_agent
        if resuming:
            same_agent = fresh
        return [self.make(job_id, "builder", same_agent if session else fresh, job["worktree"], (),
                          resume=session, fresh_prompt=fresh if session else None)]

    def reviewers(self, job_id, missing_only=False):
        job = self.cli.state(job_id)
        n, spawns = job["round"], []
        for r in job["agents"]["reviewers"]:
            own = f"round-{n}/review-{r}.md"
            if missing_only and (self.folder(job_id) / own).exists():
                continue
            role = f"reviewer-{r}"
            prompt = prompts.review(self.head(job), n, prompts.port(self.cfg, job_id, role))
            spawns.append(self.make(job_id, role, prompt, job["worktree"], (own,)))
        return spawns or self.after_reviews(job_id, [])

    def approver(self, job_id):
        job = self.cli.state(job_id)
        prompt = prompts.approve(self.head(job), job["pr"], job["round"])
        return [self.make(job_id, "approver", prompt, job["worktree"], ("decision.md",))]

    def gate(self, job_id):
        out = self.cli.gate(job_id)
        line = next((l for l in reversed(out.out.splitlines()) if l.startswith("GATE:")), None)
        if line is None:
            raise Stop(out.text)
        self.say(f"{job_id}: {line}")
        if line.startswith("GATE: PASS"):
            return self.reviewers(job_id) if self.move(job_id, "review") else []
        files = self.pr_feedback(job_id)
        prev = self.cli.state(job_id)["round"]
        if not self.next_round(job_id):
            return []
        why = " ".join([prompts.gate_failed(prev), *([prompts.pr_comments(files)] if files else [])])
        return self.builder(job_id, why)

    def merge(self, job_id):
        self.say(self.cli.job("merge", job_id).text)
        return []

    # ---- entry points ----------------------------------------------------------

    def begin(self, row):
        """(job id, first spawns) for a `resume` or `new` queue row; [] when the job needs no agent now."""
        action, issue, job_id, stage, note = (list(row) + [""] * 5)[:5]
        if action == "new":
            job_id = self.run("create", issue).strip()
            self.say(f"{job_id} #{issue}: created")
            return job_id, self.intake(job_id)
        if stage == "needs-info":
            self.move(job_id, "intake")
            return job_id, self.intake(job_id)
        if stage == "intake":
            return job_id, self.intake(job_id)
        if not self.ensure(job_id):
            return job_id, []
        if stage == "needs-human" and note.endswith(" added"):
            return job_id, self.merge(job_id) if self.move(job_id, "merging") else []
        if stage == "needs-human":
            files = self.pr_feedback(job_id)
            return job_id, self.builder(job_id, prompts.pr_arrived(files, self.cli.state(job_id)["round"]))
        steps = {"spec": self.spec_writer,
                 "build": lambda j: self.builder(j, resuming=True),
                 "gate": self.gate,
                 "review": lambda j: self.reviewers(j, missing_only=True),
                 "approve": self.approver,
                 "merging": self.merge}
        if stage not in steps:
            raise Stop(f"{job_id}: nothing to resume in {stage}")
        return job_id, steps[stage](job_id)

    def after(self, job_id, dones):
        """The next spawns once every agent in a batch has finished; [] when the job is done for this run."""
        failed = [d for d in dones if not d.ok]
        if failed:
            return self.escalate(job_id, "\n\n".join(f"{d.spawn.role}: {d.note}" for d in failed))
        role = dones[0].spawn.role
        if role == "learner":
            out = self.cli.job("learn-file", job_id)
            self.learn_files += [l for l in out.out.splitlines() if l.startswith("LEARN-FILE:")]
            if not out.ok:
                self.say(f"{job_id}: learn-file: {out.text}")
            return []
        if role.startswith("reviewer-"):
            return self.after_reviews(job_id, dones)
        handler = {"intake": self.after_intake, "spec-writer": self.after_spec,
                   "builder": self.after_builder, "approver": self.after_approver}[role]
        return handler(job_id, dones[0])

    def after_intake(self, job_id, done):
        decision = header_field(self.folder(job_id) / "intake.md", "DECISION")
        target = {"ACCEPT": "spec", "NEEDS-INFO": "needs-info", "REJECT": "rejected"}.get(decision)
        if target is None:
            return self.again(done.spawn, f"intake.md has DECISION: {decision}; it must be ACCEPT, "
                                          "NEEDS-INFO or REJECT.")
        if target == "spec":
            routed = self.cli.route(job_id)
            if not routed.ok:
                raise Stop(routed.text)
            self.say(routed.out.strip())
        try:
            moved = self.move(job_id, target)
        except Refused as e:
            return self.again(done.spawn, str(e))
        if target != "spec" or not moved or not self.ensure(job_id):
            return []
        return self.spec_writer(job_id)

    def after_spec(self, job_id, done):
        try:
            return self.builder(job_id) if self.move(job_id, "build") else []
        except Refused as e:
            return self.again(done.spawn, str(e))

    def after_builder(self, job_id, done):
        if done.session_id:
            self.run("set-session", job_id, "builder", done.session_id)
        status = first_line(self.folder(job_id) / "build.md")
        if status == "STATUS: BLOCKED":
            self.move(job_id, "needs-human")
            return []
        if status != "STATUS: READY":
            return self.again(done.spawn, f"build.md starts with {status!r}, not STATUS: READY or STATUS: BLOCKED.")
        try:
            moved = self.move(job_id, "gate")
        except Refused as e:
            return self.again(done.spawn, str(e))
        return self.gate(job_id) if moved else []

    def after_reviews(self, job_id, dones):
        self.run("sync", job_id)
        files = self.pr_feedback(job_id)
        job = self.cli.state(job_id)
        try:
            if all(v == "PASS" for v in job["reviews"].values()) and not files:
                return self.approver(job_id) if self.move(job_id, "approve") else []
            prev = job["round"]
            if not self.next_round(job_id):
                return []
        except Refused as e:
            return self.review_refused(job_id, dones, str(e))
        why = " ".join([prompts.changes(prev, prev + 1), *([prompts.pr_comments(files)] if files else [])])
        return self.builder(job_id, why)

    def review_refused(self, job_id, dones, why):
        """An invalid review: each such reviewer redoes its review once, then the job escalates."""
        bad = {f"reviewer-{r}" for r, v in self.cli.state(job_id)["reviews"].items() if v not in ("PASS", "CHANGES")}
        redo = [d.spawn for d in dones if d.spawn.role in bad]
        if not bad or not redo:
            raise Stop(why)
        spawns = []
        for spawn in redo:
            more = self.again(spawn, why)
            if not more or more[0].role != spawn.role:
                return []
            spawns += more
        return spawns

    def after_approver(self, job_id, done):
        line = first_line(self.folder(job_id) / "decision.md")
        if line == "APPROVE":
            return self.merge(job_id)
        if line == "ESCALATE":
            self.move(job_id, "needs-human")
            return []
        return self.again(done.spawn, f"decision.md starts with {line!r}, not APPROVE or ESCALATE.")

    def learn(self):
        """A learner spawn per tag `job learn` reports."""
        spawns = []
        for line in self.run("learn").splitlines():
            m = re.match(r"LEARN: (\S+) \(", line)
            if not m:
                continue
            tag = m.group(1)
            tag_dir = tag.replace(":", "--")
            folder = self.repo / "factory" / "jobs" / "learning" / tag_dir
            spawns.append(self.make(tag, "learner", prompts.learner(self.repo, tag_dir, tag), self.repo,
                                    ("proposal.md",), folder=folder))
        return spawns
