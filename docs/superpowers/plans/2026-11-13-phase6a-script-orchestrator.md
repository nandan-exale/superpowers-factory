# Phase 6a: Script Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `factory/bin/orchestrate run [<n>]`, a stdlib script, runs the factory pipeline that the `factory` skill describes today. Every agent is a headless `claude -p` child process, and the outcomes are the same as before. The runner, e2e and the `/factory` skill all call that script.

**Architecture:**
- `factory/lib/runtimes/claude.py` is the only code that knows the `claude` CLI.
- `factory/lib/orchestrator/` holds the pipeline:
  - `pipeline.py` decides each next step, from `job`/`gate`/`route` output and the agents' files.
  - `loop.py` runs the agents as processes and enforces the read-only rule.
- Agent prompts move from `.claude/agents/` to `factory/agents/`, with `access: read|write`.
- Cost comes from per-run files, `runs/NNN-<role>.json`, written by a new `job record-run`.
- `job` stays the only writer of `job.json`.

**Tech Stack:** Python 3.10+ standard library, `unittest`. `claude`, `gh` and agent behaviour are faked in tests; Task 1 records real `claude` output once.

**Spec:** `docs/superpowers/specs/2026-11-13-phase6-portable-runtime-design.md` (part 6a)

**Rules for this plan:**
- Never edit the spec or this plan. Make no git tags. Push nothing but the job branch.
- Each vendored edit goes in its own commit (`feat(vendor): …`/`fix(vendor): …`). The plugin side (tests, `bin/`, `scripts/`, `skills/`, refreshed `vendor/known-hashes.json` via `scripts/known-hashes`) goes in the next commit.
- Change nothing in the installed copy (`factory/`, `.claude/` at the repo root).
- Anchor every edit on function or heading names, not line numbers. Phases 3–5c changed these files.
- No test-only switch in vendored code. Tests load scripts as modules (`script_loader.load_script`, `FactoryProject.load_job`) or put fakes on `PATH`.
- Full check: `scripts/check`. Fast: `scripts/check --fast`. One test file: `python3 -m unittest tests.<module> -v` from the repo root.

**Behaviour that deliberately changes (everything else must not):**
1. Agents always run with `factory/runner-settings.json` and `--permission-mode dontAsk`, including from an interactive `/factory run`. Today only unattended runs used those settings.
2. The builder keeps its Claude session across factory runs (resumed by session id), where today only the same orchestrator session could resume it.
3. `job escalate` accepts any running stage, not only `review`. That is how the orchestrator stops an agent that failed twice or broke the read-only rule.
4. Job cost is the sum of `runs/*.json`. The Claude transcript scan is removed. Old jobs keep their recorded `cost_usd`, because `sync` takes the max.

**Spec items deferred to 6b:** the builder's "use Superpowers skills if your agent has them" wording, tiers, run caps, other runtimes, install from any agent. The spec's `orchestrate step <id>` is dropped, because `orchestrate run <n>` covers debugging one job. This is the only deviation from the spec's 6a scope.

---

## File structure

| File | Responsibility |
|---|---|
| `vendor/factory/factory/lib/runtimes/__init__.py` (new) | `load(name)` → adapter module |
| `vendor/factory/factory/lib/runtimes/claude.py` (new) | `build(run)` → argv/env, `parse(stdout)` → result dict, per-role tools |
| `vendor/factory/factory/lib/orchestrator/__init__.py` (new) | package marker |
| `vendor/factory/factory/lib/orchestrator/agents.py` (new) | read `factory/agents/<role>.md`: access + body |
| `vendor/factory/factory/lib/orchestrator/jobcli.py` (new) | run `job`, `gate`, `route`, `gh`; read `job.json` and config |
| `vendor/factory/factory/lib/orchestrator/prompts.py` (new) | header line and every step's prompt text |
| `vendor/factory/factory/lib/orchestrator/readonly.py` (new) | snapshot + violations for read-only roles |
| `vendor/factory/factory/lib/orchestrator/pipeline.py` (new) | `Spawn`, `Done`, `Stop`, `Pipeline.begin/after/learn` |
| `vendor/factory/factory/lib/orchestrator/loop.py` (new) | `Loop.run`: processes, retries, record-run, read-only check, queue fill, wrap-up |
| `vendor/factory/factory/bin/orchestrate` (new) | CLI entry, SIGTERM |
| `vendor/factory/factory/agents/*.md` (moved) | the nine agent prompts, frontmatter `name`, `description`, `access` |
| `vendor/factory/factory/bin/job` | `record-run`, `set-session`, run-file costs, wider `escalate` |
| `vendor/factory/factory/bin/gate` | hook finds the job from `FACTORY_JOB` |
| `vendor/factory/factory/bin/runner` | tick runs `orchestrate run` |
| `vendor/factory/factory/bin/doctor` | agents in `factory/agents/`, `orchestrate` executable |
| `vendor/factory/.claude/skills/factory/SKILL.md` | `/factory run` calls the script |
| `vendor/factory/INSTALL.md` | new paths |
| `bin/factory_files.py`, `bin/factory-update-plan`, `scripts/known-hashes` | new files, retired `.claude/agents/*.md` |
| `skills/factory-install`, `skills/factory-handoff`, `skills/factory-update`, `skills/factory-uninstall` | paths |
| `scripts/check`, `scripts/eval`, `scripts/e2e` | new agent path; e2e drives `orchestrate` |
| `tests/…` | listed per task |

---

### Task 1: Record real `claude -p` output as fixtures

This task needs a logged-in `claude` (≥ 2.1.322) and costs a few cents. It freezes the output format that `parse` is tested against.

**Files:**
- Create: `tests/fixtures/runtimes/claude/result.json`, `resumed.json`, `error.json`, `README.md`

- [ ] **Step 1: Confirm the flags exist**

Run: `claude --help | grep -E -- '--(append-system-prompt-file|effort|tools|session-id|resume|settings|permission-mode|output-format)'`
Expected: one or more lines for each of the eight flags. If any is missing, stop and report it: the adapter in Task 2 depends on all eight.

- [ ] **Step 2: Record a first run, a resumed run and an error**

```bash
D=$(mktemp -d) && cd "$D" && git init -q && echo '{}' > s.json && echo "You answer in one word." > sys.md
SID=$(python3 -c 'import uuid; print(uuid.uuid4())')
echo "Reply with the word ok." | claude -p --output-format json --model haiku --effort low \
  --append-system-prompt-file sys.md --tools Read --settings s.json --permission-mode dontAsk \
  --session-id "$SID" > result.json; echo "exit $?"
echo "Reply with the word again." | claude -p --output-format json --model haiku --effort low \
  --append-system-prompt-file sys.md --tools Read --settings s.json --permission-mode dontAsk \
  --resume "$SID" > resumed.json; echo "exit $?"
echo "Reply with ok." | claude -p --output-format json --model haiku --effort low \
  --settings s.json --permission-mode dontAsk --resume 00000000-0000-4000-8000-000000000000 > error.json 2>err.txt; echo "exit $?"
```

Expected: `exit 0`, `exit 0`, then a non-zero exit. `result.json` holds one JSON object with `"type": "result"`, `session_id` equal to `$SID`, `total_cost_usd`, `usage` and `modelUsage`. `error.json` may be empty, or hold a result with `"is_error": true`. Note which one in the README.

- [ ] **Step 3: Scrub and commit**

Replace any absolute home path in the three files with `/home/user`. Leave session ids alone; they are random UUIDs. Then copy the files to `tests/fixtures/runtimes/claude/` and write `README.md` there:

```markdown
Recorded with `claude <version>` (from `claude --version`) on <date> by the commands in
docs/superpowers/plans/2026-11-13-phase6a-script-orchestrator.md, Task 1. `error.json` is the stdout
of `--resume` with an unknown session id (exit <code>; <empty | is_error result>). Re-record when the
adapter's parse tests fail against a newer claude; never hand-edit the JSON.
```

```bash
git add tests/fixtures/runtimes/claude
git commit -m "test: recorded claude -p output for the runtime adapter"
```

---

### Task 2: Runtime package and the Claude adapter

**Files:**
- Create: `vendor/factory/factory/lib/runtimes/__init__.py`, `vendor/factory/factory/lib/runtimes/claude.py`
- Test: `tests/test_runtime_claude.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_runtime_claude.py`:

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
LIB = PLUGIN / "vendor" / "factory" / "factory" / "lib"
FIXTURES = PLUGIN / "tests" / "fixtures" / "runtimes" / "claude"
sys.path.insert(0, str(LIB))

import runtimes  # noqa: E402
from runtimes import claude  # noqa: E402


class LoadTest(unittest.TestCase):
    def test_load_claude(self):
        self.assertIs(runtimes.load("claude"), claude)

    def test_unknown_runtime_names_the_known_ones(self):
        with self.assertRaisesRegex(ValueError, "unknown runtime 'nope'; known: claude"):
            runtimes.load("nope")


class BuildTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        (self.repo / "factory").mkdir()
        (self.repo / "factory" / "runner-settings.json").write_text(json.dumps(
            {"permissions": {"deny": ["Read(./.env)"]}, "sandbox": {"enabled": True}}))
        self.runs = self.repo / "runs"
        self.runs.mkdir()

    def run_for(self, role, **extra):
        return {"repo": self.repo, "job_id": "004-x", "role": role, "access": "read", "model": "opus",
                "effort": "high", "system_path": self.runs / "s.system.md", "settings_dir": self.runs,
                "stem": "s", "resume": None, "session_id": "11111111-1111-4111-8111-111111111111", **extra}

    def test_reviewer_argv_env_and_settings(self):
        argv, env = claude.build(self.run_for("reviewer-code"))
        self.assertEqual(argv[:2], ["claude", "-p"])
        for flag, value in (("--output-format", "json"), ("--model", "opus"), ("--effort", "high"),
                            ("--append-system-prompt-file", str(self.runs / "s.system.md")),
                            ("--tools", "Read,Grep,Glob,Bash,Write"),
                            ("--settings", str(self.runs / "s.settings.json")),
                            ("--permission-mode", "dontAsk"),
                            ("--session-id", "11111111-1111-4111-8111-111111111111")):
            self.assertEqual(argv[argv.index(flag) + 1], value, flag)
        self.assertNotIn("--resume", argv)
        self.assertEqual(env, {"CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1", "FACTORY_RUNNER": "1",
                               "FACTORY_JOB": "004-x"})
        written = json.loads((self.runs / "s.settings.json").read_text())
        self.assertEqual(written, {"permissions": {"deny": ["Read(./.env)"]}, "sandbox": {"enabled": True}})

    def test_builder_gets_its_tools_and_the_gate_stop_hook(self):
        argv, _ = claude.build(self.run_for("builder", access="write"))
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob,Bash,Edit,Write,Skill")
        hooks = json.loads((self.runs / "s.settings.json").read_text())["hooks"]["Stop"]
        self.assertEqual(hooks, [{"hooks": [{"type": "command",
                                             "command": f'"{self.repo}/factory/bin/gate" --hook'}]}])

    def test_resume_replaces_session_id(self):
        argv, _ = claude.build(self.run_for("builder", access="write", resume="abc"))
        self.assertEqual(argv[argv.index("--resume") + 1], "abc")
        self.assertNotIn("--session-id", argv)

    def test_every_role_has_tools(self):
        for role in ("intake", "spec-writer", "builder", "approver", "learner",
                     "reviewer-code", "reviewer-security", "reviewer-ux", "reviewer-ui"):
            self.assertTrue(claude.tools(role), role)
        self.assertEqual(claude.tools("intake"), "Read,Grep,Glob,Write")


class ParseTest(unittest.TestCase):
    def test_recorded_result(self):
        r = claude.parse((FIXTURES / "result.json").read_text())
        self.assertFalse(r["error"])
        self.assertRegex(r["session_id"], r"^[0-9a-f-]{36}$")
        self.assertGreater(r["cost_usd"], 0)
        self.assertEqual(r["cost_source"], "cli")
        self.assertIn(r["model"], r["cost_by_model"])
        self.assertAlmostEqual(sum(r["cost_by_model"].values()), r["cost_usd"], places=4)
        self.assertIn("input_tokens", r["usage"])

    def test_recorded_resume_keeps_the_session(self):
        first = claude.parse((FIXTURES / "result.json").read_text())
        again = claude.parse((FIXTURES / "resumed.json").read_text())
        self.assertEqual(again["session_id"], first["session_id"])

    def test_recorded_error_is_an_error_or_unreadable(self):
        text = (FIXTURES / "error.json").read_text()
        try:
            self.assertTrue(claude.parse(text)["error"])
        except ValueError:
            pass

    def test_no_result_object_is_a_value_error(self):
        for text in ("", "not json", json.dumps({"type": "system"})):
            with self.assertRaises(ValueError):
                claude.parse(text)

    def test_missing_cost_is_none(self):
        r = claude.parse(json.dumps({"type": "result", "session_id": "s", "is_error": False}))
        self.assertEqual((r["cost_usd"], r["cost_source"], r["model"], r["cost_by_model"]), (None, None, None, {}))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m unittest tests.test_runtime_claude -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'runtimes'`.

- [ ] **Step 3: Write the package**

`vendor/factory/factory/lib/runtimes/__init__.py`:

```python
"""Agent CLI adapters, one module per runtime. An adapter is the only code that knows its CLI.

Every adapter has:
  NAME          its config name
  CAPS          {"resume": bool, "reports_cost": bool, "reports_tokens": bool, "efforts": [...]}
  build(run)    -> (argv, env). `run` is the dict orchestrator.loop builds: repo, job_id, role,
                   access, model, effort, system_path, settings_dir, stem, resume, session_id.
                   The prompt goes to the process on stdin.
  parse(stdout) -> {"session_id", "model", "usage", "cost_usd", "cost_source", "cost_by_model",
                   "error"}; ValueError when stdout has no result.
"""

import importlib

NAMES = ("claude",)


def load(name):
    if name not in NAMES:
        raise ValueError(f"unknown runtime {name!r}; known: {', '.join(NAMES)}")
    return importlib.import_module(f"runtimes.{name}")
```

`vendor/factory/factory/lib/runtimes/claude.py`:

```python
"""Claude Code: one `claude -p` process per agent run, prompt on stdin, one JSON result on stdout."""

import json

NAME = "claude"
CAPS = {"resume": True, "reports_cost": True, "reports_tokens": True,
        "efforts": ["low", "medium", "high", "xhigh", "max"]}

# The tools each agent had as a Claude Code subagent (its old `tools:` frontmatter).
TOOLS = {
    "intake": "Read,Grep,Glob,Write",
    "spec-writer": "Read,Grep,Glob,Bash,Write",
    "builder": "Read,Grep,Glob,Bash,Edit,Write,Skill",
    "approver": "Read,Grep,Glob,Bash,Write",
    "learner": "Read,Grep,Glob,Write,Skill",
}
REVIEWER_TOOLS = "Read,Grep,Glob,Bash,Write"


def tools(role):
    return REVIEWER_TOOLS if role.startswith("reviewer-") else TOOLS[role]


def settings(repo, role):
    """runner-settings.json for every agent; the builder also gets the gate's Stop hook, which sends
    it back to work while checks.sh fails (it was a hook in the builder's subagent frontmatter)."""
    data = json.loads((repo / "factory" / "runner-settings.json").read_text())
    if role != "builder":
        return data
    hook = {"type": "command", "command": f'"{repo}/factory/bin/gate" --hook'}
    hooks = dict(data.get("hooks") or {})
    hooks["Stop"] = [*hooks.get("Stop", []), {"hooks": [hook]}]
    return {**data, "hooks": hooks}


def build(run):
    path = run["settings_dir"] / f"{run['stem']}.settings.json"
    path.write_text(json.dumps(settings(run["repo"], run["role"]), indent=2) + "\n")
    argv = ["claude", "-p", "--output-format", "json", "--model", run["model"], "--effort", run["effort"],
            "--append-system-prompt-file", str(run["system_path"]), "--tools", tools(run["role"]),
            "--settings", str(path), "--permission-mode", "dontAsk"]
    if run.get("resume"):
        argv += ["--resume", run["resume"]]
    elif run.get("session_id"):
        argv += ["--session-id", run["session_id"]]
    # SCRUB keeps the token out of hooks and tests claude starts; FACTORY_RUNNER quiets plugin
    # SessionStart hooks; FACTORY_JOB tells the gate's Stop hook which job this is.
    env = {"CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1", "FACTORY_RUNNER": "1", "FACTORY_JOB": run["job_id"]}
    return argv, env


def result_object(stdout):
    text = stdout.strip()
    candidates = [text, *reversed(text.splitlines())]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            return data
    raise ValueError("no result object in claude's output")


def parse(stdout):
    data = result_object(stdout)
    by_model = {model: round(float(u.get("costUSD") or 0.0), 6)
                for model, u in (data.get("modelUsage") or {}).items()}
    cost = data.get("total_cost_usd")
    return {
        "session_id": data.get("session_id"),
        "model": max(by_model, key=by_model.get) if by_model else None,
        "usage": data.get("usage"),
        "cost_usd": round(float(cost), 6) if cost is not None else None,
        "cost_source": "cli" if cost is not None else None,
        "cost_by_model": by_model,
        "error": bool(data.get("is_error")),
    }
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tests.test_runtime_claude -v`
Expected: all PASS. If a parse test fails, the fixture is the truth: fix `parse`, never the fixture.

- [ ] **Step 5: Commit**

```bash
git add vendor/factory/factory/lib/runtimes
git commit -m "feat(vendor): runtime adapters, starting with claude -p"
git add tests/test_runtime_claude.py
git commit -m "test: claude adapter builds argv and parses recorded output"
```

---

### Task 3: Agent prompts move to `factory/agents/` (vendored)

**Files:**
- Move: `vendor/factory/.claude/agents/*.md` → `vendor/factory/factory/agents/*.md`
- Modify: the nine moved files (frontmatter), `vendor/factory/factory/bin/doctor` (`AGENT_KEYS`, `check_agents`), `vendor/factory/INSTALL.md`

- [ ] **Step 1: Move the files**

```bash
mkdir -p vendor/factory/factory/agents
git mv vendor/factory/.claude/agents/*.md vendor/factory/factory/agents/
```

- [ ] **Step 2: Rewrite each frontmatter**

In every file, delete the `tools:` line and add `access:` after `description:`. In `builder.md`, also delete the `hooks:` block: its five lines, from `hooks:` to the line with `gate --hook'`. The Claude adapter now installs that hook. Access: `builder` and `learner` → `write`; `intake`, `spec-writer`, `approver` and the four `reviewer-*` → `read`.

In `builder.md`'s `description`, change `Resumed with SendMessage for each new round.` to `Resumed for each new round.`. In its body, change `Load these Superpowers skills with the Skill tool and follow them:` to `Load these Superpowers skills and follow them:`.

Check:

```bash
for f in vendor/factory/factory/agents/*.md; do sed -n '1,5p' "$f"; echo; done
grep -rn "tools:\|hooks:\|SendMessage\|with the Skill tool" vendor/factory/factory/agents && echo FOUND || echo clean
```

Expected: each block is `---`, `name:`, `description:`, `access:`, `---`; the last line prints `clean`.

- [ ] **Step 3: Point doctor at the new folder**

In `vendor/factory/factory/bin/doctor`, set `AGENT_KEYS = {"name", "description", "access"}` and replace `check_agents` with:

```python
def check_agents():
    problems = []
    for name in AGENTS:
        rel = f"factory/agents/{name}.md"
        path = REPO / rel
        if not path.is_file():
            problems.append(fail(f"{rel} missing"))
            continue
        text = path.read_text(encoding="utf-8-sig")
        keys = frontmatter_keys(text)
        if keys is None:
            problems.append(fail(f"{rel}: no --- frontmatter block"))
            continue
        for key in keys:
            if key == "model":
                problems.append(fail(f"{rel}: sets model; factory/config.json sets models at spawn time"))
            elif key not in AGENT_KEYS:
                problems.append(fail(f"{rel}: unexpected frontmatter key {key!r}"))
        access = re.search(r"^access:\s*(\S+)\s*$", text, re.M)
        if not access or access.group(1) not in ("read", "write"):
            problems.append(fail(f"{rel}: access must be read or write"))
    return problems
```

In the same file, add `"factory/bin/orchestrate"` to the end of `EXECUTABLES`. `orchestrate` arrives in Task 10, and the plugin-side tests that copy vendored files run after that task.

- [ ] **Step 4: Update `vendor/factory/INSTALL.md`**

- In "## 1. Copy", replace the eight `.claude/agents/<name>.md` lines (and `learner.md` if it is listed) with `factory/agents/<name>.md` lines for all nine agents. Add `factory/bin/orchestrate` and the eight `factory/lib/…` files from this plan's file table.
- Replace every other `.claude/agents/` with `factory/agents/`.
- In "## 3. Verify", item 3 becomes: ``Each file in `factory/agents/` has only these frontmatter keys: `name`, `description` and `access` (`read` or `write`). No agent sets `model`: `factory/config.json` does, at spawn time.``
- In "## 4. Hand over", ``run `/factory run` in Claude Code`` becomes ``run `/factory run` in Claude Code, or `factory/bin/orchestrate run` in a terminal``.

Check: `grep -n "\.claude/agents" vendor/factory/INSTALL.md` prints nothing.

- [ ] **Step 5: Commit (vendored only)**

```bash
git add -A vendor/factory/.claude/agents vendor/factory/factory/agents vendor/factory/factory/bin/doctor vendor/factory/INSTALL.md
git commit -m "feat(vendor): agent prompts move to factory/agents with an access level"
```

The plugin-side tests are red until Task 4. Don't run `scripts/check` yet.

---

### Task 4: Plugin side of the move

**Files:**
- Modify: `bin/factory_files.py`, `scripts/known-hashes`, `bin/factory-update-plan`, `scripts/check`, `scripts/eval`, `skills/factory-install/SKILL.md`, `skills/factory-handoff/SKILL.md`, `skills/factory-update/SKILL.md`, `skills/factory-uninstall/SKILL.md`, `tests/installed_project.py`
- Test: `tests/test_check.py`, `tests/test_doctor.py`, `tests/test_dogfood_wording.py`, `tests/test_factory_update.py`, `tests/test_handoff_skill.py`, `tests/test_factory_uninstall_skill.py`, `tests/test_eval.py`, new `tests/test_retired_agents.py`

- [ ] **Step 1: Write the failing test for retired files**

`tests/test_retired_agents.py`:

```python
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import factory_files as ff  # noqa: E402


def sha(data):
    return hashlib.sha256(data).hexdigest()


class RetiredAgentsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name)
        self.known = self.project / "known.json"
        old = b"---\nname: approver\n---\nold\n"
        self.known.write_text(json.dumps({".claude/agents/approver.md": [sha(old)]}))
        (self.project / ".claude/agents").mkdir(parents=True)
        (self.project / ".claude/agents/approver.md").write_bytes(old)
        (self.project / ".claude/agents/builder.md").write_text("my own edits\n")

    def plan(self, *extra):
        env = {**os.environ, "FACTORY_KNOWN_HASHES": str(self.known)}
        return subprocess.run([sys.executable, str(REPO / "bin/factory-update-plan"), str(self.project), *extra],
                              capture_output=True, text=True, env=env)

    def test_retired_lists_every_old_agent_path(self):
        self.assertEqual(set(ff.RETIRED), {f".claude/agents/{n}.md" for n in ff.AGENTS})

    def test_unedited_old_copy_is_retired_and_edited_one_is_flagged(self):
        out = self.plan().stdout
        self.assertRegex(out, r"retired\s+\.claude/agents/approver\.md")
        self.assertRegex(out, r"retired-edited\s+\.claude/agents/builder\.md")

    def test_apply_safe_deletes_only_unedited_retired_files(self):
        res = self.plan("--apply-safe")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((self.project / ".claude/agents/approver.md").exists())
        self.assertTrue((self.project / ".claude/agents/builder.md").exists())


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -m unittest tests.test_retired_agents -v`
Expected: FAIL (`factory_files` has no `RETIRED`).

- [ ] **Step 2: `bin/factory_files.py`**

Replace the `.claude/agents` entry in `FILES` and add the new files and `RETIRED`:

```python
LIB = ("factory/lib/runtimes/__init__.py", "factory/lib/runtimes/claude.py",
       "factory/lib/orchestrator/__init__.py", "factory/lib/orchestrator/agents.py",
       "factory/lib/orchestrator/jobcli.py", "factory/lib/orchestrator/prompts.py",
       "factory/lib/orchestrator/readonly.py", "factory/lib/orchestrator/pipeline.py",
       "factory/lib/orchestrator/loop.py")
FILES = (
    ".claude/skills/factory/SKILL.md",
    *(f"factory/agents/{name}.md" for name in AGENTS),
    *LIB,
    "factory/bin/orchestrate",
    # … every other existing entry, unchanged …
)
# Paths earlier versions installed and this one doesn't: /factory-update removes unedited copies.
RETIRED = tuple(f".claude/agents/{name}.md" for name in AGENTS)
```

The `LIB` and `orchestrate` entries point at files created in Tasks 6–10. `test_every_listed_file_exists_in_vendor` stays red until Task 10. That is expected; the other tests in this task must pass.

- [ ] **Step 3: `scripts/known-hashes` keeps the retired files' history**

Import `RETIRED` next to `FILES`. In `generate`, use `sorted({*FILES, *RETIRED})`. `missing` keeps checking only `FILES`.

Run: `scripts/known-hashes && git diff --stat vendor/known-hashes.json`
Expected: the `.claude/agents/*.md` keys keep their hashes, and the `factory/agents/*.md` keys appear with the moved files' history.

- [ ] **Step 4: `bin/factory-update-plan` classifies retired files**

Import `RETIRED`. At the end of `classify`, before `return rows`:

```python
    for rel in RETIRED:
        path = project / rel
        if not path.exists():
            continue
        mine = sha256_file(path)
        unedited = mine in known.get(rel, ()) or mine == (base or {}).get(rel)
        rows.append(("retired" if unedited else "retired-edited", rel))
```

In `apply_safe`, after the copy loop:

```python
    for group, rel in rows:
        if group == "retired":
            (project / rel).unlink()
```

`new_manifest` must not list retired paths. `manifest_data` already lists only `FILES`, so nothing changes there. Confirm that `main` prints rows as `group<TAB>path` (or however it prints the others), so the regexes in Step 1 match. Adjust the regexes to the real separator if it differs.

- [ ] **Step 5: Skills**

- `skills/factory-install/SKILL.md`, Step 1 (Copy) loop: replace the `.claude/agents/…` names with `factory/agents/intake.md … factory/agents/learner.md` (all nine). Add the nine `LIB` paths and `factory/bin/orchestrate`. Add `factory/bin/orchestrate` to the `chmod +x` line. `test_install_skill_copies_every_listed_file` checks this.
- `skills/factory-handoff/SKILL.md`: `` `.claude/agents/approver.md` `` → `` `factory/agents/approver.md` ``.
- `skills/factory-update/SKILL.md`, step 1, add two groups to the list:
  - `` `retired`: files earlier versions installed and this one no longer uses (the old `.claude/agents/`), unedited here, so they will be deleted; ``
  - `` `retired-edited`: the same, but edited in this project: show the diff against `factory/agents/<name>.md` and carry the project's changes into that file (the new copy is the one the factory reads), then delete the old file. ``
- `skills/factory-uninstall/SKILL.md`: wherever it lists `.claude/agents`, list `factory/agents` and `factory/lib` instead, and keep `.claude/agents` as "if present (installs before 0.5.0)".

- [ ] **Step 6: `scripts/check` and `scripts/eval`**

- `scripts/check` `FRONTMATTER_GLOBS`: `"vendor/factory/.claude/agents/*.md"` → `"vendor/factory/factory/agents/*.md"`.
- `scripts/eval`:
  - Set `AGENTS = VENDOR / "factory" / "agents"`.
  - `agent_prompt(agent)` returns `(body, tools)`, with tools from the adapter: load `VENDOR / "factory/lib/runtimes/claude.py"` with `importlib.machinery.SourceFileLoader("factory_claude_runtime", …)` once at module level, then call `CLAUDE_RUNTIME.tools(agent).split(",")`.
  - Delete the frontmatter `tools:` parsing; keep the frontmatter-closed check.

- [ ] **Step 7: Fix tests that name the old paths**

```bash
git grep -ln "\.claude/agents" -- tests
```

In each file listed, change `.claude/agents/` to `factory/agents/` (for vendored paths, `vendor/factory/.claude/agents/` → `vendor/factory/factory/agents/`), with two exceptions:
- `tests/test_factory_update.py`: the test that tailors `.claude/agents/reviewer-ui.md` now tailors `factory/agents/reviewer-ui.md`.
- `tests/test_doctor.py`: the test that adds `color: red` still expects `unexpected frontmatter key 'color'`. Add a test that `access: maybe` fails with `access must be read or write`.

In `tests/installed_project.py`, the copied file list comes from the same pattern. Make it `factory/agents/{name}.md`, plus the `LIB` files and `factory/bin/orchestrate` (import them from `factory_files`). In `tests/test_dogfood_wording.py`, `BUILDER` reads `VENDOR / "factory/agents/builder.md"`.

- [ ] **Step 8: Run what can pass now**

```bash
python3 -m unittest tests.test_retired_agents tests.test_check tests.test_doctor tests.test_dogfood_wording \
  tests.test_factory_update tests.test_handoff_skill tests.test_factory_uninstall_skill tests.test_eval -v
```

Expected: PASS. A failure that names a missing `factory/lib/…` or `factory/bin/orchestrate` file is expected until Task 10. Any other failure is a bug in this task.

- [ ] **Step 9: Commit**

```bash
git add bin scripts skills tests vendor/known-hashes.json
git commit -m "feat: install, update and checks follow the agents to factory/agents"
```

---

### Task 5: `job` records runs, keeps the builder's session, and costs from run files (vendored)

**Files:**
- Modify: `vendor/factory/factory/bin/job` (usage docstring; cost section "Cost from Claude Code transcripts"; `log_learning_cost`; `evidence_md`; `cmd_costs`; `cmd_escalate`; `main`)
- Test: `tests/test_runs.py` (new); rewrite `tests/test_cost_by_model.py`; update `tests/test_learning.py`, `tests/budget_case.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_runs.py`:

```python
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import FactoryProject  # noqa: E402


class RunsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.project.set_issue("Build it.", labels=("factory",))
        self.job = self.project.load_job()
        self.job_id = self.project.create_job(self.job)
        self.d = self.job.job_dir(self.job_id)

    def main(self, *argv, stdin=""):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin)), contextlib.redirect_stdout(out):
            self.job.main(list(argv))
        return out.getvalue()

    def record(self, role, cost, model="claude-opus-5-5"):
        run = {"runtime": "claude", "model": model, "effort": "high", "session_id": "s", "exit": 0,
               "cost_usd": cost, "cost_source": "cli" if cost is not None else None,
               "cost_by_model": {model: cost} if cost is not None else {}}
        return self.main("record-run", self.job_id, role, stdin=json.dumps(run))

    def test_record_run_numbers_files_and_updates_cost(self):
        self.assertIn("runs/001-intake.json", self.record("intake", 1.5))
        self.assertIn("runs/002-builder.json", self.record("builder", 2.25, "claude-sonnet-5-5"))
        saved = json.loads((self.d / "runs" / "002-builder.json").read_text())
        self.assertEqual((saved["seq"], saved["role"], saved["cost_usd"]), (2, "builder", 2.25))
        job = json.loads((self.d / "job.json").read_text())
        self.assertAlmostEqual(job["cost_usd"], 3.75)
        self.assertEqual(self.job.cost_by_model(self.d), {"claude-opus-5-5": 1.5, "claude-sonnet-5-5": 2.25})

    def test_unknown_cost_counts_nothing(self):
        self.record("intake", None)
        self.assertEqual(self.job.cost_for_folder(self.d), 0.0)

    def test_other_files_in_runs_are_not_runs(self):
        (self.d / "runs").mkdir()
        (self.d / "runs" / "20261113T000000000000Z-builder.settings.json").write_text("{}")
        self.assertEqual(self.job.run_files(self.d), [])

    def test_record_run_refuses_bad_stdin(self):
        with self.assertRaises(SystemExit):
            self.main("record-run", self.job_id, "intake", stdin="nope")

    def test_learner_runs_go_to_the_learning_folder(self):
        self.main("record-run", "missing-test", "learner",
                  stdin=json.dumps({"cost_usd": 0.5, "cost_by_model": {"claude-opus-5-5": 0.5}}))
        self.assertTrue((self.job.tag_dir("missing-test") / "runs" / "001-learner.json").exists())
        self.assertEqual(self.job.cost_for_folder(self.job.tag_dir("missing-test")), 0.5)

    def test_set_session_keeps_other_fields(self):
        self.main("set-session", self.job_id, "builder", "abc-123")
        job = json.loads((self.d / "job.json").read_text())
        self.assertEqual(job["sessions"], {"builder": "abc-123"})
        self.assertEqual(job["issue"], 7)

    def test_escalate_works_from_spec(self):
        job = self.job.load(self.job_id)
        self.job.save({**job, "stage": "spec"})
        self.main("escalate", self.job_id, stdin="the spec writer failed twice")
        job = json.loads((self.d / "job.json").read_text())
        self.assertEqual(job["stage"], "needs-human")
        self.assertIn("failed twice", (self.d / "decision.md").read_text())

    def test_escalate_refuses_a_waiting_job(self):
        job = self.job.load(self.job_id)
        self.job.save({**job, "stage": "needs-info"})
        with self.assertRaises(SystemExit):
            self.main("escalate", self.job_id, stdin="x")


if __name__ == "__main__":
    unittest.main()
```

Rewrite `tests/test_cost_by_model.py` so it writes run files instead of transcripts. Keep its four test names and expectations:
- `transcript(name, model, input_tokens)` becomes `run(name, model, usd)`, which writes `<folder>/runs/<NNN>-<name>.json` with `{"cost_usd": usd, "cost_by_model": {model: usd}}`.
- `cost_by_model(needle)` calls become `cost_by_model(folder)`, and `cost_for_needle` becomes `cost_for_folder`.
- `test_other_jobs_do_not_count` uses two job folders.

In `tests/test_learning.py`:
- `self.job.cost_for_needle = lambda needle: self.learner_cost` becomes `self.job.cost_for_folder = lambda folder: self.learner_cost`.
- In the class that uses `write_transcript`, replace the transcript with a run file in `tag_dir("missing-test") / "runs" / "001-learner.json"` costing `4.0`. Keep `test_learn_file_logs_the_cost_…`'s assertions (delta 4.0, daily spend 4.0).
- Delete `test_relative_job_folder_does_not_match` and `test_skill_prompt_form_is_the_absolute_job_folder_form`. The prompt no longer carries cost, so there is nothing for them to check.

`tests/budget_case.py` replaces `cost_usd`, and that still works; drop its `CLAUDE_CONFIG_DIR` patch. Run `git grep -n CLAUDE_CONFIG_DIR tests` and remove the env setting from `test_job_planned.py`, `test_pr_feedback.py` and `test_routing.py`; nothing reads it any more.

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m unittest tests.test_runs tests.test_cost_by_model -v`
Expected: FAIL (`bad arguments: record-run …`, missing `cost_for_folder`).

- [ ] **Step 3: Implement**

Replace the whole "Cost from Claude Code transcripts" section (`transcripts_dir`, `prompt_text`, `cost_usd`, `cost_by_model`, `cost_for_needle`) with:

```python
# ---- Cost from agent runs --------------------------------------------------

RUN_FILE = "[0-9][0-9][0-9]-*.json"


def run_files(folder):
    """The folder's agent runs, runs/NNN-<role>.json, oldest first."""
    d = folder / "runs"
    return sorted(d.glob(RUN_FILE)) if d.exists() else []


def cost_by_model(folder):
    """{model: cost} over the folder's agent runs. A run whose cost is unknown counts nothing."""
    totals = {}
    for path in run_files(folder):
        try:
            run = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            print(f"job: skipping {path}: {exc}", file=sys.stderr)
            continue
        by_model = run.get("cost_by_model") or (
            {run.get("model") or "unknown": run["cost_usd"]} if run.get("cost_usd") is not None else {})
        for model, usd in by_model.items():
            totals[model] = totals.get(model, 0.0) + float(usd)
    return {model: round(usd, 2) for model, usd in totals.items()}


def cost_for_folder(folder):
    return round(sum(cost_by_model(folder).values()), 2)


def cost_usd(job):
    return cost_for_folder(job_dir(job["id"]))


def record_run(folder, role, text):
    try:
        data = json.loads(text)
    except ValueError as exc:
        die(f"record-run: stdin isn't JSON: {exc}")
    if not isinstance(data, dict):
        die("record-run: stdin must be a JSON object")
    d = folder / "runs"
    d.mkdir(parents=True, exist_ok=True)
    seq = len(list(d.glob(RUN_FILE))) + 1
    path = d / f"{seq:03d}-{role}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**data, "seq": seq, "role": role}, indent=2) + "\n")
    tmp.replace(path)
    return path
```

Keep `model_summary` as it is. Then update the callers:
- `cmd_costs(job)`: `by_model = cost_by_model(job_dir(job["id"]))`.
- `evidence_md`: `model_summary(cost_by_model(job_dir(job["id"])))`.
- `log_learning_cost(tag)`: `total = round(cost_for_folder(tag_dir(tag)), 6)`.
- Check `git grep -n "cost_for_needle\|prompt_text\|transcripts_dir\|Job folder:" vendor/factory/factory/bin/job`. It must print nothing.

Replace `cmd_escalate`:

```python
ESCALATABLE = {"intake", "spec", "build", "gate", "review", "approve"}


def cmd_escalate(job, why):
    """A running job → needs-human with your reason: a reviewer that keeps writing an invalid review,
    or an agent the orchestrator gave up on."""
    require(job["stage"] in ESCALATABLE, f"{job['id']} is in {job['stage']}, not a running stage")
    require(why.strip(), "no reason on stdin")
    stop_for_human(job, why.strip())
```

Add the commands in `main`, before the final `else`:

```python
        elif cmd == "record-run" and len(args) == 2 and args[1] == "learner":
            print(record_run(tag_dir(args[0]), "learner", sys.stdin.read()).relative_to(REPO))
        elif cmd == "record-run" and len(args) == 2:
            job = resolve(args[0])
            path = record_run(job_dir(job["id"]), args[1], sys.stdin.read())
            save(sync(job))
            print(path.relative_to(REPO))
        elif cmd == "set-session" and len(args) == 3:
            job = resolve(args[0])
            save({**job, "sessions": {**(job.get("sessions") or {}), args[1]: args[2]}})
            print(f"{job['id']}: {args[1]} session {args[2]}")
```

A learner tag isn't a job: check `TAG_NAME.fullmatch(args[0])` in the learner branch, as `cmd_agent_learner` does, and `die` otherwise.

In the usage docstring, change the `job escalate` line to `job escalate <job>             a running job → needs-human, with your reason (stdin) as decision.md`, and add:

```
  job record-run <job> <role>    an agent run's result (JSON, stdin) → runs/NNN-<role>.json; refreshes cost
                                 (learner: <job> is a learning tag)
  job set-session <job> <role> <id>  remember a role's agent session id, so the next round resumes it
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tests.test_runs tests.test_cost_by_model tests.test_learning tests.test_budgets tests.test_evidence tests.test_report -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vendor/factory/factory/bin/job
git commit -m "feat(vendor): job records agent runs and costs them from run files"
git add tests
git commit -m "test: run files, sessions and wider escalate"
```

---

### Task 6: The gate's hook finds its job from `FACTORY_JOB` (vendored)

**Files:**
- Modify: `vendor/factory/factory/bin/gate` (`hook`)
- Test: `tests/test_gate_env.py` (add a class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gate_env.py` (it already loads the gate; follow its existing setup for a job with a worktree and a failing `checks.sh`):

```python
class HookJobFromEnvTest(GateHookCase):
    def test_factory_job_env_wins_over_the_transcript(self):
        event = {"stop_hook_active": False, "transcript_path": "/nonexistent"}
        code, err = self.run_hook(event, env={"FACTORY_JOB": self.job_id})
        self.assertEqual(code, 2)
        self.assertIn("checks.sh fails in your worktree", err)
```

`GateHookCase` and `run_hook` are names for whatever helper the file already has to run `gate --hook` with a JSON event on stdin. Reuse it. If no hook test exists yet, write `run_hook` with `subprocess.run([sys.executable, gate, "--hook"], input=json.dumps(event), env={**os.environ, **env}, capture_output=True, text=True)` against a `FactoryProject` whose `factory/checks.sh` is `exit 1`.

- [ ] **Step 2: Run it to see it fail**

Run: `python3 -m unittest tests.test_gate_env -v`
Expected: FAIL with `FileNotFoundError: /nonexistent`.

- [ ] **Step 3: Implement**

In `hook`, replace the lines from `with open(Path(event["agent_transcript_path"])…` through `job_id = …` with:

```python
    job_id = os.environ.get("FACTORY_JOB") or job_from_transcript(event)
```

and add above `hook`:

```python
def job_from_transcript(event):
    """The job id from the first prompt line `Job: <id>.` of a subagent's transcript."""
    path = event.get("agent_transcript_path") or event["transcript_path"]
    with open(Path(path).expanduser()) as f:
        content = json.loads(f.readline())["message"]["content"]
    prompt = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content)
    return prompt.split("Job: ", 1)[1].split(".", 1)[0]
```

Change the docstring line `gate --hook  builder SubagentStop hook: …` to `gate --hook  the builder's Stop hook: run the checks once, exit 2 on failure`.

- [ ] **Step 4: Run, then commit**

Run: `python3 -m unittest tests.test_gate_env -v` → PASS.

```bash
git add vendor/factory/factory/bin/gate
git commit -m "feat(vendor): gate hook reads the job from FACTORY_JOB"
git add tests/test_gate_env.py
git commit -m "test: gate hook job from the environment"
```

---

### Task 7: Orchestrator helpers: agents, jobcli, prompts (vendored)

**Files:**
- Create: `vendor/factory/factory/lib/orchestrator/__init__.py` (empty docstring only), `agents.py`, `jobcli.py`, `prompts.py`
- Test: `tests/test_orchestrator_helpers.py`

- [ ] **Step 1: Write the failing tests**

```python
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


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -m unittest tests.test_orchestrator_helpers -v` → FAIL (`No module named 'orchestrator'`).

- [ ] **Step 2: Implement**

`orchestrator/__init__.py`:

```python
"""The factory's orchestrator: factory/bin/orchestrate runs it."""
```

`orchestrator/agents.py`:

```python
"""Agent prompts: factory/agents/<role>.md, frontmatter (name, description, access) then the body."""

from pathlib import Path

ACCESS = ("read", "write")


def load(repo, role):
    """{"access": "read" | "write", "body": prompt text}; ValueError for a malformed file."""
    path = Path(repo) / "factory" / "agents" / f"{role}.md"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError(f"{path}: no --- frontmatter block")
    end = lines.index("---", 1)
    meta = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    if meta.get("access") not in ACCESS:
        raise ValueError(f"{path}: access must be read or write, not {meta.get('access')!r}")
    return {"access": meta["access"], "body": "\n".join(lines[end + 1:]).strip() + "\n"}
```

`orchestrator/jobcli.py`:

```python
"""The scripts the orchestrator changes state through (job, gate, route), plus gh and job.json reads."""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Out:
    code: int
    out: str
    err: str

    @property
    def ok(self):
        return self.code == 0

    @property
    def text(self):
        return "\n".join(t for t in (self.out.strip(), self.err.strip()) if t)


class JobCli:
    def __init__(self, repo):
        self.repo = Path(repo)
        self.bin = self.repo / "factory" / "bin"

    def _run(self, argv, stdin=None):
        res = subprocess.run(argv, cwd=self.repo, input=stdin, capture_output=True, text=True)
        return Out(res.returncode, res.stdout, res.stderr)

    def job(self, *args, stdin=None):
        return self._run([sys.executable, str(self.bin / "job"), *map(str, args)], stdin)

    def gate(self, job_id):
        return self._run([sys.executable, str(self.bin / "gate"), job_id])

    def route(self, job_id):
        return self._run([sys.executable, str(self.bin / "route"), job_id])

    def gh(self, *args):
        return self._run(["gh", *map(str, args)])

    def state(self, job_id):
        return json.loads((self.repo / "factory" / "jobs" / job_id / "job.json").read_text())

    def config(self):
        return json.loads((self.repo / "factory" / "config.json").read_text())
```

`orchestrator/prompts.py`:

```python
"""Every prompt the orchestrator sends, worded as the factory skill worded it for the agents."""

PORT_OFFSET = {"builder": 0, "reviewer-ux": 1, "reviewer-ui": 2}
RESUMING = ("You are resuming a build another builder started: read build.md and `git log` to see how "
            "far it got (and, when plan.md exists, which plan tasks are ticked off), then carry on.")


def header(repo, job, base, worktree=True):
    where = (f"Worktree: {job['worktree']}." if worktree
             else "Worktree: none, it doesn't exist yet. Work in the main checkout.")
    line = (f"Job: {job['id']}. Job folder: {repo}/factory/jobs/{job['id']}/. Main checkout: {repo}. "
            f"{where} Branch: {job['branch']}. Base: origin/{base}. Issue: #{job['issue']}.")
    if job.get("tasks"):
        line += f" Tasks: {job['tasks']} of {job['plan_tasks']}."
    return line


def port(config, job_id, role):
    """The port an agent may serve pages on, or None for roles that open no pages."""
    if role not in PORT_OFFSET:
        return None
    ports = config.get("ports") or {"base": 5100, "step": 10}
    return ports["base"] + ports["step"] * int(job_id.split("-", 1)[0]) + PORT_OFFSET[role]


def build(head, n, port_, why=""):
    return f"{head} Build round {n}. Port: {port_}." + (f" {why}" if why else "")


def review(head, n, port_):
    return f"{head} Review round {n}." + (f" Port: {port_}." if port_ is not None else "")


def approve(head, pr, n):
    return f"{head} PR: #{pr}. Final round: {n}."


def learner(repo, tag_dir, tag):
    return f"Job folder: {repo}/factory/jobs/learning/{tag_dir}/. {tag}"


def gate_failed(prev):
    return f"The gate failed: read round-{prev}/checks.md and checks.log, fix it, push, and update build.md."


def changes(prev, n):
    return (f"Round {prev} reviews are in round-{prev}/. Address every VERDICT: CHANGES, push, "
            f"and update build.md for round {n}.")


def pr_comments(files):
    return f"Also address PR comments in {' '.join(files)}."


def pr_arrived(files, n):
    return f"PR comments arrived: read {' '.join(files)} and address them, push, and update build.md for round {n}."


def refused(text):
    return f"The factory refused your result:\n\n{text}\n\nFix that, then reply again."
```

- [ ] **Step 3: Run, then commit**

Run: `python3 -m unittest tests.test_orchestrator_helpers -v` → PASS.

```bash
git add vendor/factory/factory/lib/orchestrator
git commit -m "feat(vendor): orchestrator helpers for agents, scripts and prompts"
git add tests/test_orchestrator_helpers.py
git commit -m "test: orchestrator helpers"
```

---

### Task 8: Read-only check (vendored)

**Files:**
- Create: `vendor/factory/factory/lib/orchestrator/readonly.py`
- Test: `tests/test_readonly.py`

- [ ] **Step 1: Write the failing tests**

```python
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "vendor" / "factory" / "factory" / "lib"))

from orchestrator import readonly  # noqa: E402


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class ReadOnlyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.tree = root / "wt"
        self.tree.mkdir()
        git(self.tree, "init", "-q")
        git(self.tree, "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "x")
        self.folder = root / "job"
        (self.folder / "round-1").mkdir(parents=True)
        (self.folder / "job.json").write_text("{}")
        self.before = readonly.snapshot(self.folder, self.tree, compare_head=True)

    def after(self):
        return readonly.snapshot(self.folder, self.tree, compare_head=True)

    def test_own_file_and_bookkeeping_are_fine(self):
        (self.folder / "round-1" / "review-code.md").write_text("VERDICT: PASS\n")
        (self.folder / "job.json").write_text('{"x": 1}')
        (self.folder / "runs").mkdir()
        (self.folder / "runs" / "001-reviewer-code.json").write_text("{}")
        self.assertEqual(readonly.violations(self.before, self.after(), {"round-1/review-code.md"}), [])

    def test_another_file_in_the_job_folder(self):
        (self.folder / "spec.md").write_text("rewritten")
        problems = readonly.violations(self.before, self.after(), {"round-1/review-code.md"})
        self.assertEqual(problems, ["wrote files it doesn't own: spec.md"])

    def test_worktree_change(self):
        (self.tree / "new.py").write_text("x")
        problems = readonly.violations(self.before, self.after(), set())
        self.assertEqual(len(problems), 1)
        self.assertIn("changed the checkout", problems[0])
        self.assertIn("new.py", problems[0])

    def test_head_ignored_for_the_main_checkout(self):
        before = readonly.snapshot(self.folder, self.tree, compare_head=False)
        git(self.tree, "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "y")
        self.assertEqual(readonly.violations(before, readonly.snapshot(self.folder, self.tree, compare_head=False),
                                             set()), [])

    def test_quarantine_moves_own_files_into_runs(self):
        (self.folder / "round-1" / "review-code.md").write_text("VERDICT: PASS\n")
        readonly.quarantine(self.folder, {"round-1/review-code.md", "decision.md"})
        self.assertFalse((self.folder / "round-1" / "review-code.md").exists())
        self.assertTrue((self.folder / "runs" / "round-1--review-code.md.rejected").exists())


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -m unittest tests.test_readonly -v` → FAIL (import).

- [ ] **Step 2: Implement**

```python
"""The rule for read-only agents: the checkout stays as it was, and only the role's own files in the job
folder change. Checked by comparing snapshots taken before and after the agents run."""

import subprocess

BOOKKEEPING = {"job.json", "job.tmp", "log.jsonl", ".lock", "evidence.md"}


def folder_files(folder):
    files = {}
    for path in folder.rglob("*"):
        rel = path.relative_to(folder).as_posix()
        if path.is_file() and rel.split("/", 1)[0] != "runs" and rel not in BOOKKEEPING:
            st = path.stat()
            files[rel] = (st.st_mtime_ns, st.st_size)
    return files


def git_out(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout


def snapshot(folder, checkout, compare_head):
    """compare_head is False for the main checkout, which other jobs' merges may fast-forward."""
    return {
        "files": folder_files(folder),
        "head": git_out(checkout, "rev-parse", "HEAD").strip() if compare_head else None,
        "status": git_out(checkout, "status", "--porcelain", "--untracked-files=all"),
    }


def violations(before, after, own):
    problems = []
    if before["head"] != after["head"] or before["status"] != after["status"]:
        was, now = set(before["status"].splitlines()), set(after["status"].splitlines())
        changed = sorted((was ^ now)) or ["HEAD moved"]
        problems.append("changed the checkout: " + ", ".join(line.strip() for line in changed))
    keys = set(before["files"]) | set(after["files"])
    changed = sorted(k for k in keys if before["files"].get(k) != after["files"].get(k))
    stray = [k for k in changed if k not in own]
    if stray:
        problems.append("wrote files it doesn't own: " + ", ".join(stray))
    return problems


def quarantine(folder, own):
    """Move a rejected run's own files to runs/, so the next step doesn't read them as valid."""
    (folder / "runs").mkdir(exist_ok=True)
    for rel in sorted(own):
        path = folder / rel
        if path.exists():
            path.rename(folder / "runs" / (rel.replace("/", "--") + ".rejected"))
```

- [ ] **Step 3: Run, then commit**

Run: `python3 -m unittest tests.test_readonly -v` → PASS.

```bash
git add vendor/factory/factory/lib/orchestrator/readonly.py
git commit -m "feat(vendor): read-only check for agents that may only write their own file"
git add tests/test_readonly.py
git commit -m "test: read-only check"
```

---

### Task 9: The pipeline (vendored)

`Pipeline` turns queue rows and finished agent batches into the next batch of `Spawn`s. It never touches processes. Every rule below is the factory skill's "Advancing a job", "/factory run" and "Resuming" sections, as code. Where this plan and the skill disagree, the skill wins; report the difference.

**Files:**
- Create: `vendor/factory/factory/lib/orchestrator/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "vendor" / "factory" / "factory" / "lib"))

from orchestrator import pipeline  # noqa: E402
from orchestrator.jobcli import Out  # noqa: E402
from orchestrator.pipeline import Done, Pipeline  # noqa: E402

CONFIG = {"base_branch": "main", "labels": {"planned": "factory:planned"},
          "ports": {"base": 5100, "step": 10}}


class FakeCli:
    """job/gate/route/gh answered from `answers` ({args tuple prefix: Out}); job.json from `jobs`."""

    def __init__(self, repo):
        self.repo = repo
        self.calls = []
        self.answers = {}
        self.jobs = {}

    def answer(self, *prefix, code=0, out="", err=""):
        self.answers[prefix] = Out(code, out, err)

    def _reply(self, args, stdin=None):
        self.calls.append((args, stdin))
        for n in range(len(args), 0, -1):
            if args[:n] in self.answers:
                return self.answers[args[:n]]
        if args[0] == "agent":
            return Out(0, "model=opus effort=high\n", "")
        return Out(0, "", "")

    def job(self, *args, stdin=None):
        return self._reply(("job", *map(str, args)), stdin)

    def gate(self, job_id):
        return self._reply(("gate", job_id))

    def route(self, job_id):
        return self._reply(("route", job_id))

    def gh(self, *args):
        return self._reply(("gh", *map(str, args)))

    def state(self, job_id):
        return self.jobs[job_id]

    def config(self):
        return CONFIG

    def called(self, *prefix):
        return [a for a, _ in self.calls if a[:len(prefix)] == prefix]


class PipelineCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.folder = self.repo / "factory" / "jobs" / "004-x"
        (self.folder / "round-1").mkdir(parents=True)
        self.cli = FakeCli(self.repo)
        self.lines = []
        self.p = Pipeline(self.cli, say=self.lines.append)
        self.cli.jobs["004-x"] = {"id": "004-x", "issue": 12, "stage": "intake", "round": 0,
                                  "worktree": str(self.repo / ".worktrees/004-x"), "branch": "factory/004-x",
                                  "pr": None, "agents": None, "reviews": {}}
        self.cli.answer("job", "ensure-worktree", "004-x", out="WORKTREE: 004-x present\n")

    def set(self, **fields):
        self.cli.jobs["004-x"] = {**self.cli.jobs["004-x"], **fields}

    def write(self, rel, text):
        (self.folder / rel).write_text(text)

    def done(self, spawn, ok=True, session=None, note=""):
        return Done(spawn, ok, session, note)

    def only(self, spawns):
        self.assertEqual(len(spawns), 1, spawns)
        return spawns[0]


class StartTest(PipelineCase):
    def test_new_issue_goes_to_intake_in_the_main_checkout(self):
        self.cli.answer("job", "create", "12", out="004-x\n")
        self.cli.answer("gh", "issue", "view", out="factory\n")
        job_id, spawns = self.p.begin(("new", "12", "-", "-", "Title"))
        s = self.only(spawns)
        self.assertEqual((job_id, s.role, s.cwd, s.own), ("004-x", "intake", self.repo, ("intake.md",)))
        self.assertIn("Worktree: none, it doesn't exist yet.", s.prompt)
        self.assertEqual((s.model, s.effort), ("opus", "high"))

    def test_planned_issue_skips_intake_and_builds(self):
        self.cli.answer("gh", "issue", "view", out="factory\nfactory:planned\n")
        self.cli.answer("job", "planned", "004-x", out="PLANNED: 004-x → build (code)\n")
        self.set(stage="build", round=1)
        _, spawns = self.p.begin(("resume", "12", "004-x", "intake", "round 0"))
        s = self.only(spawns)
        self.assertEqual(s.role, "builder")
        self.assertTrue(s.prompt.endswith("Build round 1. Port: 5140."))
        self.assertIsNone(s.resume)

    def test_refused_plan_finishes_the_job(self):
        self.cli.answer("gh", "issue", "view", out="factory:planned\n")
        self.cli.answer("job", "planned", "004-x", out="PLANNED: REFUSED bad block\n")
        self.assertEqual(self.p.begin(("resume", "12", "004-x", "intake", ""))[1], [])
        self.assertIn("PLANNED: REFUSED bad block", self.lines)

    def test_resume_build_resumes_the_stored_session(self):
        self.set(stage="build", round=2, sessions={"builder": "sess-1"})
        s = self.only(self.p.begin(("resume", "12", "004-x", "build", "round 2"))[1])
        self.assertEqual(s.resume, "sess-1")
        self.assertIn(pipeline.prompts.RESUMING, s.prompt)
        self.assertIn(pipeline.prompts.RESUMING, s.fresh_prompt)

    def test_resume_review_spawns_only_missing_reviewers(self):
        self.set(stage="review", round=1, agents={"reviewers": {"code": {}, "ux": {}}})
        self.write("round-1/review-code.md", "VERDICT: PASS\n")
        s = self.only(self.p.begin(("resume", "12", "004-x", "review", ""))[1])
        self.assertEqual((s.role, s.own), ("reviewer-ux", ("round-1/review-ux.md",)))
        self.assertTrue(s.prompt.endswith("Review round 1. Port: 5141."))

    def test_lost_worktree_finishes_the_job(self):
        self.set(stage="spec")
        self.cli.answer("job", "ensure-worktree", "004-x", out="004-x: needs-human: worktree gone\n")
        self.assertEqual(self.p.begin(("resume", "12", "004-x", "spec", ""))[1], [])


class AfterTest(PipelineCase):
    def spawn(self, role, own=("x",), prompt="P"):
        return pipeline.Spawn("004-x", role, prompt, self.repo, self.folder, own)

    def test_intake_accept_routes_and_spawns_the_spec_writer(self):
        self.write("intake.md", "DECISION: ACCEPT\nRISK: low\n\nbody\n")
        self.cli.answer("job", "advance", "004-x", "spec", out="004-x: spec (round 0)\n")
        s = self.only(self.p.after("004-x", [self.done(self.spawn("intake"))]))
        self.assertEqual((s.role, s.own), ("spec-writer", ("spec.md",)))
        self.assertEqual(self.cli.called("route"), [("route", "004-x")])

    def test_intake_with_a_bad_decision_is_asked_once_then_escalated(self):
        self.write("intake.md", "DECISION: MAYBE\n")
        again = self.only(self.p.after("004-x", [self.done(self.spawn("intake", ("intake.md",)))]))
        self.assertIn("The factory refused your result", again.prompt)
        self.assertEqual(self.p.after("004-x", [self.done(again)]), [])
        self.assertEqual(len(self.cli.called("job", "escalate", "004-x")), 1)

    def test_builder_ready_gate_pass_spawns_reviewers_with_ports(self):
        self.write("build.md", "STATUS: READY\n")
        self.set(stage="build", round=1, agents={"reviewers": {"code": {}, "ui": {}}})
        self.cli.answer("gate", "004-x", out="GATE: PASS (004-x round 1, …)\n")
        spawns = self.p.after("004-x", [self.done(self.spawn("builder"), session="sess-9")])
        self.assertEqual([s.role for s in spawns], ["reviewer-code", "reviewer-ui"])
        self.assertTrue(spawns[1].prompt.endswith("Port: 5142."))
        self.assertIn(("job", "set-session", "004-x", "builder", "sess-9"), self.cli.called("job"))
        self.assertIn(("job", "advance", "004-x", "gate"), self.cli.called("job"))
        self.assertIn(("job", "advance", "004-x", "review"), self.cli.called("job"))

    def test_gate_fail_sends_the_builder_back_with_pr_comments(self):
        self.write("build.md", "STATUS: READY\n")
        self.set(stage="build", round=1, sessions={"builder": "sess-9"})
        self.cli.answer("gate", "004-x", code=1, out="GATE: FAIL (004-x round 1)\n")
        self.cli.answer("job", "pr-feedback", "004-x", out="PR-FEEDBACK: feedback-1.md (1 new comments)\n")
        s = self.only(self.p.after("004-x", [self.done(self.spawn("builder"))]))
        self.assertEqual(s.resume, "sess-9")
        self.assertIn(pipeline.prompts.gate_failed(1), s.prompt)
        self.assertIn("Also address PR comments in feedback-1.md.", s.prompt)

    def test_gate_fail_in_the_last_round_goes_to_needs_human(self):
        self.write("build.md", "STATUS: READY\n")
        self.set(stage="build", round=3)
        self.cli.answer("gate", "004-x", code=1, out="GATE: FAIL\n")
        self.cli.answer("job", "advance", "004-x", "build", code=1, err="job: round 3 of 3: go to needs-human")
        self.assertEqual(self.p.after("004-x", [self.done(self.spawn("builder"))]), [])
        self.assertIn(("job", "advance", "004-x", "needs-human"), self.cli.called("job"))

    def test_builder_blocked_goes_to_needs_human(self):
        self.write("build.md", "STATUS: BLOCKED\n")
        self.assertEqual(self.p.after("004-x", [self.done(self.spawn("builder"))]), [])
        self.assertIn(("job", "advance", "004-x", "needs-human"), self.cli.called("job"))

    def test_reviews_all_pass_spawn_the_approver(self):
        self.set(stage="review", round=2, pr=30, reviews={"code": "PASS"})
        s = self.only(self.p.after("004-x", [self.done(self.spawn("reviewer-code"))]))
        self.assertEqual((s.role, s.own), ("approver", ("decision.md",)))
        self.assertTrue(s.prompt.endswith("PR: #30. Final round: 2."))

    def test_review_changes_send_the_builder_back(self):
        self.set(stage="review", round=1, reviews={"code": "CHANGES"})
        s = self.only(self.p.after("004-x", [self.done(self.spawn("reviewer-code"))]))
        self.assertEqual(s.role, "builder")
        self.assertIn(pipeline.prompts.changes(1, 2), s.prompt)

    def test_invalid_review_is_redone_once_then_escalated(self):
        self.set(stage="review", round=1, reviews={"code": "invalid"})
        self.cli.answer("job", "advance", "004-x", code=1, err="job: review-code.md has no VERDICT line")
        again = self.only(self.p.after("004-x", [self.done(self.spawn("reviewer-code"))]))
        self.assertEqual(again.role, "reviewer-code")
        self.assertIn("no VERDICT line", again.prompt)
        self.assertEqual(self.p.after("004-x", [self.done(again)]), [])
        self.assertEqual(len(self.cli.called("job", "escalate", "004-x")), 1)

    def test_approve_merges_and_escalate_goes_to_needs_human(self):
        self.write("decision.md", "APPROVE\n")
        self.assertEqual(self.p.after("004-x", [self.done(self.spawn("approver"))]), [])
        self.assertEqual(self.cli.called("job", "merge"), [("job", "merge", "004-x")])
        self.write("decision.md", "ESCALATE\n")
        self.p.after("004-x", [self.done(self.spawn("approver"))])
        self.assertIn(("job", "advance", "004-x", "needs-human"), self.cli.called("job"))

    def test_failed_agent_escalates_with_its_note(self):
        self.assertEqual(self.p.after("004-x", [self.done(self.spawn("spec-writer"), ok=False,
                                                          note="exit 1 twice")]), [])
        (args, stdin), = [(a, s) for a, s in self.cli.calls if a[:2] == ("job", "escalate")]
        self.assertIn("spec-writer: exit 1 twice", stdin)

    def test_budget_stop_ends_the_job(self):
        self.write("build.md", "STATUS: READY\n")
        self.cli.answer("job", "advance", "004-x", "gate", out="BUDGET: 004-x → needs-human (budget: $30 of $25)\n")
        self.assertEqual(self.p.after("004-x", [self.done(self.spawn("builder"))]), [])
        self.assertIn("BUDGET: 004-x → needs-human (budget: $30 of $25)", self.lines)

    def test_daily_budget_stops_the_job_and_flags_the_run(self):
        self.write("spec.md", "spec")
        self.cli.answer("job", "advance", "004-x", "build", code=1, err="job: daily budget: $100 of $100")
        with self.assertRaises(pipeline.Stop):
            self.p.after("004-x", [self.done(self.spawn("spec-writer"))])
        self.assertTrue(self.p.daily)


class LearnTest(PipelineCase):
    def test_learn_spawns_a_learner_per_tag(self):
        self.cli.answer("job", "learn", out="LEARN: other:x (3 jobs) factory/jobs/learning/other--x/evidence.md\n")
        s = self.only(self.p.learn())
        self.assertEqual((s.job_id, s.role, s.own), ("other:x", "learner", ("proposal.md",)))
        self.assertEqual(s.folder, self.repo / "factory" / "jobs" / "learning" / "other--x")
        self.assertEqual(s.prompt, f"Job folder: {self.repo}/factory/jobs/learning/other--x/. other:x")
        self.assertIn(("job", "agent", "other:x", "learner"), self.cli.called("job"))

    def test_after_learner_files_the_proposal(self):
        self.cli.answer("job", "learn-file", "other:x", out="LEARN-FILE: other:x #42\n")
        s = pipeline.Spawn("other:x", "learner", "P", self.repo, self.folder, ("proposal.md",))
        self.assertEqual(self.p.after("other:x", [Done(s, True)]), [])
        self.assertEqual(self.p.learn_files, ["LEARN-FILE: other:x #42"])


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -m unittest tests.test_pipeline -v` → FAIL (import).

- [ ] **Step 2: Implement `pipeline.py`**

```python
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
        action, issue, job_id, _stage, note = (list(row) + [""] * 5)[:5]
        if action == "new":
            job_id = self.run("create", issue).strip()
            self.say(f"{job_id} #{issue}: created")
            return job_id, self.intake(job_id)
        stage = self.cli.state(job_id)["stage"]
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
```

`again` for reviewers: when a reviewer was already retried, `again` escalates and returns `[]`, so `review_refused` returns `[]`. `job escalate` works from `review`.

- [ ] **Step 3: Run the tests**

Run: `python3 -m unittest tests.test_pipeline -v`
Expected: PASS. If a test fails because the plan's code misreads a script's output format, check the script in `vendor/factory/factory/bin/job` and fix the code, not the test's meaning.

- [ ] **Step 4: Commit**

```bash
git add vendor/factory/factory/lib/orchestrator/pipeline.py
git commit -m "feat(vendor): the factory pipeline as code"
git add tests/test_pipeline.py
git commit -m "test: pipeline steps, retries, budgets and learning"
```

---

### Task 10: The process loop and `bin/orchestrate` (vendored)

**Files:**
- Create: `vendor/factory/factory/lib/orchestrator/loop.py`, `vendor/factory/factory/bin/orchestrate` (mode 755)
- Test: `tests/test_loop.py`

- [ ] **Step 1: Write the failing tests**

The loop is tested with a fake pipeline, the `FakeCli` from `tests/test_pipeline.py` (import it), and a fake runtime whose "CLI" is a Python script. The script writes the role's own file, prints a JSON result, and exits with `$FAKE_EXIT_<role>` (default 0).

```python
import json
import os
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


if __name__ == "__main__":
    unittest.main()
```

`own_for` maps a role to the file the fake agent writes, and `env` adds `FAKE_*` switches for one test.

Run: `python3 -m unittest tests.test_loop -v` → FAIL (import).

- [ ] **Step 2: Implement `loop.py`**

```python
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
        data = {"runtime": self.rt.NAME, "model": p.get("model") or spawn.model, "effort": spawn.effort,
                "session_id": p.get("session_id"), "started": record["started"], "ended": utc(), "exit": code,
                "usage": p.get("usage"), "cost_usd": p.get("cost_usd"), "cost_source": p.get("cost_source"),
                "cost_by_model": p.get("cost_by_model") or {}, "log": f"runs/{record['stem']}.log"}
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
```

- [ ] **Step 3: Write `bin/orchestrate`**

```python
#!/usr/bin/env python3
"""Run the software factory: the pipeline the factory skill describes, as a script. Every agent is a
child process of the configured runtime (config.json `runtime`, default claude).

Usage:
  orchestrate run          drain the queue: every open `factory` issue, `concurrency` at a time; also resumes
  orchestrate run <n>      run one issue now

It prints one line per step and ends with `job summary` and `SPENT: $<usd>`. SIGTERM stops every agent;
state is in files, so the next run resumes.
"""

import signal
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "factory" / "lib"))

import runtimes  # noqa: E402
from orchestrator.jobcli import JobCli  # noqa: E402
from orchestrator.loop import Loop  # noqa: E402
from orchestrator.pipeline import Pipeline  # noqa: E402


def say(line):
    print(line, flush=True)


def main(argv):
    if not argv or argv[0] != "run" or len(argv) > 2 or (len(argv) == 2 and not argv[1].isdigit()):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cli = JobCli(REPO)
    runtime = runtimes.load(cli.config().get("runtime", "claude"))
    loop = Loop(cli, Pipeline(cli, say=say), runtime, say=say)

    def on_sigterm(signum, frame):
        loop.stop()
        say("stopped")
        sys.exit(1)

    signal.signal(signal.SIGTERM, on_sigterm)
    return loop.run(int(argv[1]) if len(argv) == 2 else None)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

```bash
chmod 755 vendor/factory/factory/bin/orchestrate
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tests.test_loop tests.test_pipeline -v` → PASS.

- [ ] **Step 5: Commit (vendored), then refresh hashes**

```bash
git add vendor/factory/factory/lib/orchestrator/loop.py vendor/factory/factory/bin/orchestrate
git commit -m "feat(vendor): orchestrate runs the pipeline with agents as child processes"
scripts/known-hashes
python3 -m unittest tests.test_factory_manifest tests.test_doctor -v
git add tests/test_loop.py vendor/known-hashes.json
git commit -m "test: orchestrator loop, retries, read-only rule and stop"
```

Expected: `test_factory_manifest` is now green, including `test_every_listed_file_exists_in_vendor`.

---

### Task 11: The `/factory` skill calls the script (vendored)

**Files:**
- Modify: `vendor/factory/.claude/skills/factory/SKILL.md`
- Test: `tests/test_orchestrate_wording.py` (new)

- [ ] **Step 1: Write the failing test**

```python
import unittest
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[1] / "vendor/factory/.claude/skills/factory/SKILL.md").read_text()


class SkillWordingTest(unittest.TestCase):
    def test_run_goes_through_the_script(self):
        self.assertIn("factory/bin/orchestrate run", SKILL)

    def test_no_claude_code_spawning_left(self):
        for word in ("subagent_type", "SendMessage", "Agent tool", "WAIT FOR ALL"):
            self.assertNotIn(word, SKILL, word)

    def test_talking_to_the_factory_is_kept(self):
        for text in ("factory/bin/job feedback", "factory/bin/job reject", "factory/bin/job resume",
                     "gh issue create --label factory", "factory/bin/job report"):
            self.assertIn(text, SKILL, text)


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -m unittest tests.test_orchestrate_wording -v` → FAIL.

- [ ] **Step 2: Rewrite the skill**

Keep the frontmatter, the `# Factory` intro (with "You are the factory's only orchestrator" changed to "`factory/bin/orchestrate` is the factory's orchestrator; you start it and talk to the user"), the command block, "## The pipeline" and "## Files" (with the agent paths now `factory/agents/`). Keep "## /factory report", "## /factory <anything>" and "## Guardrails" as they are.

Delete "## Spawning agents", "## Advancing a job", "## /factory run" and "## /factory run <n>", and put in their place:

```markdown
## /factory run

Run `factory/bin/orchestrate run` from the main checkout, in the background
(it can take hours), and tell the user it started. It runs the whole pipeline
(watch, queue, every agent as its own `claude` process, gate, reviews, merge,
learning, report and digest) and prints one line per step. When it finishes,
show its last lines: the `job summary` table, any `LEARN-FILE:`, `DIGEST:` or
`PAUSED:` lines, and `SPENT:`. Then list what waits on a human (run
`factory/bin/job queue` and explain each `wait` line, as under
**What needs them** below).

Don't spawn agents, advance jobs or run the gate yourself while it runs: it is
the only orchestrator. If it exits non-zero, show its last 20 lines. If
starting it is blocked in this session, tell the user to run
`factory/bin/orchestrate run` in a terminal from the project root.

## /factory run <n>

The same, with `factory/bin/orchestrate run <n>`: one issue, resumed if it
has a job. Finish with its summary line.
```

In "## /factory <anything>", where it says "go to **build**" (feedback) or "do **/factory run <n>**" (new feature, needs-info answer), replace that with "then run `factory/bin/orchestrate run <n>` as under **/factory run <n>**".

- [ ] **Step 3: Run, then commit**

```bash
python3 -m unittest tests.test_orchestrate_wording tests.test_visibility_wording tests.test_safety_wording tests.test_parts_wording -v
```

If an older wording test asserts a sentence that existed only in a deleted section, check whether the behaviour behind it is now in `pipeline.py` or `loop.py`. If it is, change that test to assert the behaviour in code (for example, `tests.test_pipeline` for `ensure-worktree`). Never delete a check without moving it.

```bash
git add vendor/factory/.claude/skills/factory/SKILL.md
git commit -m "feat(vendor): /factory run starts factory/bin/orchestrate"
git add tests
scripts/known-hashes && git add vendor/known-hashes.json
git commit -m "test: the factory skill hands the run to the script"
```

---

### Task 12: The runner ticks `orchestrate` (vendored)

**Files:**
- Modify: `vendor/factory/factory/bin/runner` (`PROMPT`, `CHILD`, `run_claude`, `on_sigterm`, `prune_runs`, `cost_of`, `tick_body`)
- Test: `tests/test_runner.py`, `tests/test_runner_linux.py`, `tests/test_runner_ci.py`, `tests/installed_project.py`

- [ ] **Step 1: Change the tests first**

In each runner test file, the fake that records calls is installed on `PATH` as `claude`. Install the same script at `<project>/factory/bin/orchestrate` instead (overwriting the vendored copy in the throwaway project, mode 755), recording `"tool": "orchestrate"`. Keep a fake `claude` on `PATH` too, because the tick still checks that it exists. Then:

- Every assertion that the recorded argv is `["-p", "/factory run", …]` becomes `call["argv"] == ["run"]`.
- The env assertions (`has_token`, `has_api_key`, `has_base_url`, `scrub == "1"`, `runner == "1"`) stay, now on the orchestrate call.
- The fake prints `SPENT: $1.25` as its last line instead of the JSON result. Assertions on `cost=$1.25` in `runner.log` stay.
- Add one test to `tests/test_runner.py`: with no `claude` on `PATH`, `tick` logs `error: claude not found on PATH` and doesn't start `orchestrate`.

Run: `python3 -m unittest tests.test_runner tests.test_runner_linux tests.test_runner_ci -v` → FAIL (the runner still calls `claude`).

- [ ] **Step 2: Implement**

In `runner`:
- Delete `PROMPT`. Change `CHILD`'s comment to `# the running orchestrate process, for the SIGTERM handler`. Add `ORCHESTRATE = FACTORY / "bin" / "orchestrate"`.
- Rename `run_claude` to `run_orchestrate`. Keep its env lines exactly (token, `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`, `GIT_ENV`, `FACTORY_RUNNER`); the agents inherit them. Its command becomes:

```python
    cmd = [sys.executable, str(ORCHESTRATE), "run"]
```

- Output files: `out_path = RUNS / f"{stamp().replace(':', '')}.out"`. The err path keeps `.stderr.log`. `prune_runs` strips `.out` instead of `.json`. Update its docstring: `(a run is its .out plus .stderr.log)`.
- `cost_of(path)`:

```python
def cost_of(path):
    """The SPENT line orchestrate ends with, or ?."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return "?"
    spent = [l for l in lines if l.startswith("SPENT: $")]
    return spent[-1].removeprefix("SPENT: ") if spent else "?"
```

- In `tick_body`, before `max_seconds`:

```python
    if not shutil.which("claude"):
        log("error: claude not found on PATH")
        return 1
```

  Then call `run_orchestrate(...)`. In the `except` branches, change "claude" to "orchestrate" (`could not start orchestrate`), and delete the `FileNotFoundError` branch: `sys.executable` always exists.
- Module docstring: `run /factory run headless` → `run factory/bin/orchestrate run`.

- [ ] **Step 3: Run, then commit**

Run: `python3 -m unittest tests.test_runner tests.test_runner_linux tests.test_runner_ci -v` → PASS.

```bash
git add vendor/factory/factory/bin/runner
git commit -m "feat(vendor): runner ticks factory/bin/orchestrate"
scripts/known-hashes
git add tests vendor/known-hashes.json
git commit -m "test: runner starts orchestrate with the token in its environment"
```

---

### Task 13: e2e drives `orchestrate`

**Files:**
- Modify: `scripts/e2e` (`one_session`), `tests/e2e_sandbox.py`, `tests/test_e2e.py`

- [ ] **Step 1: Tests first**

In `tests/e2e_sandbox.py`:
- Write `FAKE_CLAUDE`'s body (renamed `FAKE_ORCHESTRATE`) to the sandbox as `factory/bin/orchestrate` (via `write_exe`, before the `init` commit). Make it record `{"tool": "orchestrate", "argv": …}` and print `SPENT: $<FAKE_SESSION_COST>` instead of the JSON result line.
- Keep a fake `claude` on `PATH` that only records its call.
- Add `orchestrate_calls()` next to `claude_calls()`.

In `tests/test_e2e.py`:
- `test_a_passing_scenario`: replace the three `claude` assertions with `(call,) = self.sb.orchestrate_calls(); self.assertEqual(call["argv"], ["run"]); self.assertEqual((call["runner"], call["scrub"]), ("1", "1"))`.
- Every other `self.sb.claude_calls()` becomes `self.sb.orchestrate_calls()`.

Run: `python3 -m unittest tests.test_e2e -v` → FAIL.

- [ ] **Step 2: Implement**

In `scripts/e2e` `one_session`, the non-runner command becomes:

```python
        cmd = [str(r.sandbox / "factory" / "bin" / "orchestrate"), "run"]
```

Its env comes from `run_session` (`RUN_ENV`). Check that `RUN_ENV` sets `FACTORY_RUNNER=1` and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`; the test asserts it. `session_cost(text)` reads JSON, which `orchestrate` doesn't print. Make it read the last `SPENT: $x` line. The `Spend` docstring stays true: job logs count the agents, so set `add_session` to add `0.0` for orchestrate runs, or drop the call. Keep the cap's arithmetic tested by `test_e2e.py`'s existing spend tests.

- [ ] **Step 3: Run, then commit**

Run: `python3 -m unittest tests.test_e2e tests.test_e2e_scenarios -v` → PASS.

```bash
git add scripts/e2e tests/e2e_sandbox.py tests/test_e2e.py
git commit -m "feat: e2e drives factory/bin/orchestrate"
```

---

### Task 14: Docs, full check, and the real-run proof

**Files:**
- Modify: `README.md`, `AGENTS.md`, `docs/superpowers/specs/2026-11-13-roadmap.md`

- [ ] **Step 1: Docs**

- `AGENTS.md` "Map":
  - `.claude/skills/factory` is the orchestrator's entry point; `factory/bin/orchestrate` (with `factory/lib/orchestrator/`) is the orchestrator.
  - `factory/lib/runtimes/` holds the agent CLI adapters.
  - `factory/agents/` holds the agents.
  - The installed-copy bullet lists `factory/agents/` instead of `.claude/agents/`.
- `README.md`: the file table row `` `.claude/agents/reviewer-*.md` `` becomes `` `factory/agents/reviewer-*.md` ``. Where it says to run `/factory run`, add "or `factory/bin/orchestrate run` from a terminal". Add one line saying that each agent is its own `claude -p` process and that `factory/jobs/<id>/runs/` holds every run's prompt, log and cost.
- Roadmap: in the phase 6 row, set Plan to `plans/2026-11-13-phase6a-script-orchestrator.md` (6b: to be written after 6a merges) and Status to `6a planned`.

- [ ] **Step 2: Full check**

Run: `scripts/check`
Expected: every line `PASS`. Fix causes, not tests. If `branding` fails, a new file mentions an upstream name: reword it.

- [ ] **Step 3: Commit**

```bash
git add README.md AGENTS.md docs/superpowers/specs/2026-11-13-roadmap.md
git commit -m "docs: the orchestrator script, agents folder and run files"
```

- [ ] **Step 4: Prove "no behaviour change" on a real run (human, costs money)**

This step runs on the maintainer's machine, not in a factory job. A factory builder writes `STATUS: READY` with this step listed under `## Deviations` as `For the human: run scripts/e2e on the 6a branch`.

```bash
scripts/e2e --sandbox <the guarded sandbox repo> --max-usd 15
```

Expected: every scenario has the same outcome it had on v0.4.0 (`tests/e2e/*/scenario.json` expectations), and each job folder in the sandbox has `runs/NNN-*.json` files whose costs add up to `job.json` `cost_usd`. Then say in the PR whether `scripts/eval` ran (agent prompts changed: frontmatter and two sentences in `builder.md`). Commit a baseline change only with the run that produced it.

---

## Self-review notes (for the executor)

- `job` remains the only writer of `job.json`. `record-run` and `set-session` are `job` subcommands, and the orchestrator only reads `job.json`.
- Every new file is listed in `bin/factory_files.py` `FILES` (Task 4), `skills/factory-install/SKILL.md` (Task 4), `vendor/factory/INSTALL.md` (Task 3) and `vendor/known-hashes.json` (refreshed in Tasks 4, 10, 11, 12).
- After Task 4 and before Task 10, `tests.test_factory_manifest.test_every_listed_file_exists_in_vendor` and the doctor `files` check fail, because those files don't exist yet. Don't "fix" this by trimming `FILES`.
