# Configurable Models and Effort Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every factory agent's model and effort comes from `factory/config.json`; no agent file or prompt fixes a model.

**Architecture:** `config.json` gains `model_aliases`, `effort_levels`, `agents.intake`, and `{model, effort}` entries per role in `routing`/`surface_reviewers`. `bin/job` gets `route` (stores every later agent's setting in `job.json`) and `agent` (prints one role's setting); `bin/route` becomes a wrapper. Agent files lose `model:`; the orchestrator passes `model` and `effort` on every spawn.

**Tech Stack:** Python 3.10+ stdlib, `unittest`, Markdown prompts.

**Spec:** `docs/superpowers/specs/2026-11-12-configurable-models-design.md`

**Repo root:** `/Users/nandanthakur/projects/superpowers-factory`. Run tests with `python3 -m unittest discover -s tests -v` (33 pass before this plan).

---

### Task 1: Config-driven routing in `bin/job`

**Files:**
- Modify: `vendor/factory/factory/config.json` (`routing`, `surface_reviewers`; new keys)
- Modify: `vendor/factory/factory/bin/job` (`route_agents`, `cmd_agents` → `cmd_route`, new `cmd_agent`, docstring, `main`)
- Modify: `vendor/factory/factory/bin/route` (whole file)
- Modify: `tests/factory_project.py` (copy `route` too)
- Modify: `tests/test_job_planned.py:59` and `:80` (new `agents` shape)
- Create: `tests/test_routing.py`

- [ ] **Step 1: Copy `bin/route` into the test project**

In `tests/factory_project.py`, replace:

```python
        shutil.copy(VENDOR / "factory" / "bin" / "job", self.repo / "factory" / "bin" / "job")
```

with:

```python
        for script in ("job", "route"):
            shutil.copy(VENDOR / "factory" / "bin" / script, self.repo / "factory" / "bin" / script)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_routing.py`:

```python
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest

from factory_project import FactoryProject

INTAKE = "DECISION: {decision}\nRISK: {risk}\nSURFACES: {surfaces}\nRESCOPED: no\n\n## Summary\n- test\n"
LOW = {
    "spec-writer": {"model": "opus", "effort": "medium"},
    "builder": {"model": "opus", "effort": "medium"},
    "approver": {"model": "opus", "effort": "medium"},
    "reviewers": {"code": {"model": "haiku", "effort": "medium"}},
}


class RoutingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp.name
        self.project = FactoryProject(self.tmp.name)
        self.project.set_issue("Build the widget.", labels=("factory",))
        self.job = self.project.load_job()
        self.job_id = self.project.create_job(self.job)
        self.d = self.job.job_dir(self.job_id)

    def tearDown(self):
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.tmp.cleanup()

    def accept(self, risk="low", surfaces="none", decision="ACCEPT"):
        (self.d / "intake.md").write_text(INTAKE.format(decision=decision, risk=risk, surfaces=surfaces))

    def edit_config(self, change):
        """Change the project's config.json and re-import bin/job. Call before any load()."""
        path = self.project.repo / "factory" / "config.json"
        config = json.loads(path.read_text())
        change(config)
        path.write_text(json.dumps(config))
        self.job = self.project.load_job()

    def current(self):
        return self.job.sync(self.job.load(self.job_id))

    def route(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_route(self.current())
        return out.getvalue()

    def agent(self, role):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_agent(self.current(), role)
        return out.getvalue().strip()

    def refused(self, fragment):
        with self.assertRaises(self.job.Refused) as ctx:
            self.route()
        self.assertIn(fragment, str(ctx.exception))


class RouteTest(RoutingTestCase):
    def test_low_risk_no_surfaces(self):
        self.accept("low")
        self.route()
        self.assertEqual(self.job.load(self.job_id)["agents"], LOW)

    def test_high_risk_with_surfaces(self):
        self.accept("high", "ui, security")
        self.route()
        agents = self.job.load(self.job_id)["agents"]
        self.assertEqual(agents["builder"], {"model": "opus", "effort": "high"})
        self.assertEqual(agents["reviewers"], {
            "code": {"model": "sonnet", "effort": "high"},
            "ux": {"model": "sonnet", "effort": "medium"},
            "ui": {"model": "haiku", "effort": "medium"},
            "security": {"model": "opus", "effort": "high"},
        })

    def test_route_prints_every_agent(self):
        self.accept("low")
        out = self.route()
        self.assertIn("builder opus/medium", out)
        self.assertIn("code haiku/medium", out)

    def test_route_refuses_job_intake_did_not_accept(self):
        self.accept("low", decision="REJECT")
        with self.assertRaises(SystemExit):
            self.route()


class RouteValidationTest(RoutingTestCase):
    def test_unknown_model(self):
        self.edit_config(lambda c: c["routing"]["low"]["builder"].update(model="gpt"))
        self.accept("low")
        self.refused("routing.low.builder.model 'gpt' isn't in model_aliases")

    def test_unknown_effort(self):
        self.edit_config(lambda c: c["routing"]["low"]["builder"].update(effort="ludicrous"))
        self.accept("low")
        self.refused("routing.low.builder.effort 'ludicrous' isn't in effort_levels")

    def test_missing_role(self):
        self.edit_config(lambda c: c["routing"]["low"].pop("approver"))
        self.accept("low")
        self.refused("routing.low is missing: approver")

    def test_old_string_setting(self):
        self.edit_config(lambda c: c["routing"]["low"].update(code="haiku"))
        self.accept("low")
        self.refused("routing.low.code must be {model, effort}")

    def test_bad_surface_setting(self):
        self.edit_config(lambda c: c["surface_reviewers"]["ui"]["ux"].update(model="gpt"))
        self.accept("low", "ui")
        self.refused("surface_reviewers.ui.ux.model 'gpt'")

    def test_unknown_surface(self):
        self.accept("low", "billing")
        self.refused("surface 'billing' isn't in config.json surface_reviewers")

    def test_unknown_risk(self):
        self.accept("spicy")
        self.refused("risk 'spicy' isn't in config.json routing")


class AgentTest(RoutingTestCase):
    def test_intake_from_config(self):
        self.assertEqual(self.agent("intake"), "model=fable effort=high")

    def test_routed_agent_and_reviewer(self):
        self.accept("medium", "ui")
        self.route()
        self.assertEqual(self.agent("builder"), "model=opus effort=high")
        self.assertEqual(self.agent("reviewer-ux"), "model=sonnet effort=medium")

    def test_role_before_routing_exits(self):
        with self.assertRaises(SystemExit):
            self.agent("builder")

    def test_reviewer_not_routed_exits(self):
        self.accept("low")
        self.route()
        with self.assertRaises(SystemExit):
            self.agent("reviewer-ux")

    def test_bad_intake_config_refused(self):
        self.edit_config(lambda c: c["agents"]["intake"].update(model="gpt"))
        with self.assertRaises(self.job.Refused) as ctx:
            self.agent("intake")
        self.assertIn("agents.intake.model 'gpt'", str(ctx.exception))


class RouteWrapperTest(RoutingTestCase):
    def test_bin_route_runs_job_route(self):
        self.accept("low")
        res = subprocess.run([str(self.project.repo / "factory" / "bin" / "route"), self.job_id],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("code haiku/medium", res.stdout)
        self.assertEqual(json.loads((self.d / "job.json").read_text())["agents"], LOW)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run to verify they fail**

Run: `python3 -m unittest discover -s tests -p "test_routing.py" -v`
Expected: errors for `cmd_route` / `cmd_agent` missing (`AttributeError`), and the wrapper test fails.

- [ ] **Step 4: Rewrite the routing config**

In `vendor/factory/factory/config.json`, replace from the line `  "routing": {` through the closing `  },` of `surface_reviewers` with:

```json
  "model_aliases": ["fable", "opus", "sonnet", "haiku"],
  "effort_levels": ["low", "medium", "high", "xhigh", "max"],
  "agents": {
    "intake": { "model": "fable", "effort": "high" }
  },
  "routing": {
    "low": {
      "spec-writer": { "model": "opus",   "effort": "medium" },
      "builder":     { "model": "opus",   "effort": "medium" },
      "approver":    { "model": "opus",   "effort": "medium" },
      "code":        { "model": "haiku",  "effort": "medium" }
    },
    "medium": {
      "spec-writer": { "model": "opus",   "effort": "high" },
      "builder":     { "model": "opus",   "effort": "high" },
      "approver":    { "model": "opus",   "effort": "high" },
      "code":        { "model": "sonnet", "effort": "high" }
    },
    "high": {
      "spec-writer": { "model": "opus",   "effort": "high" },
      "builder":     { "model": "opus",   "effort": "high" },
      "approver":    { "model": "opus",   "effort": "high" },
      "code":        { "model": "sonnet", "effort": "high" }
    }
  },
  "surface_reviewers": {
    "ui": {
      "ux": { "model": "sonnet", "effort": "medium" },
      "ui": { "model": "haiku",  "effort": "medium" }
    },
    "security": {
      "security": { "model": "opus", "effort": "high" }
    }
  },
```

Verify: `python3 -m json.tool vendor/factory/factory/config.json >/dev/null && echo ok` → `ok`.

- [ ] **Step 5: Replace `route_agents` in `bin/job`**

Replace the whole current `route_agents` function (the one whose docstring starts "factory/bin/route's lookup, in-process") with:

```python
AGENT_ROLES = ("spec-writer", "builder", "approver")


def agent_setting(where, setting):
    """A config `{model, effort}` entry, checked against model_aliases and effort_levels."""
    require(isinstance(setting, dict) and set(setting) == {"model", "effort"},
            f"{where} must be {{model, effort}}, got {setting!r}")
    aliases, levels = CONFIG["model_aliases"], CONFIG["effort_levels"]
    require(setting["model"] in aliases,
            f"{where}.model {setting['model']!r} isn't in model_aliases ({', '.join(aliases)})")
    require(setting["effort"] in levels,
            f"{where}.effort {setting['effort']!r} isn't in effort_levels ({', '.join(levels)})")
    return dict(setting)


def route_agents(risk, surfaces):
    """Model and effort for every agent after intake, from config.json `routing`
    and `surface_reviewers`. `job route` and `job planned` both call it."""
    table = CONFIG["routing"].get(risk)
    require(table is not None, f"risk {risk!r} isn't in config.json routing ({', '.join(CONFIG['routing'])})")
    missing = [r for r in (*AGENT_ROLES, "code") if r not in table]
    require(not missing, f"routing.{risk} is missing: {', '.join(missing)}")
    settings = {name: agent_setting(f"routing.{risk}.{name}", s) for name, s in table.items()}
    reviewers = {name: s for name, s in settings.items() if name not in AGENT_ROLES}
    for surface in surfaces:
        extra = CONFIG["surface_reviewers"].get(surface)
        require(extra is not None, f"surface {surface!r} isn't in config.json surface_reviewers "
                                   f"({', '.join(CONFIG['surface_reviewers'])})")
        reviewers.update({name: agent_setting(f"surface_reviewers.{surface}.{name}", s)
                          for name, s in extra.items()})
    return {**{r: settings[r] for r in AGENT_ROLES}, "reviewers": reviewers}
```

- [ ] **Step 6: Replace `cmd_agents` with `cmd_route` and `cmd_agent`**

Replace the whole `cmd_agents` function with:

```python
def cmd_route(job):
    if job["stage"] != "intake" or (job["intake"] or {}).get("decision") != "ACCEPT":
        die(f"{job['id']}: route only an intake job that intake ACCEPTed")
    job["agents"] = route_agents(job["intake"]["risk"], job["intake"]["surfaces"])
    save(job)
    settings = {**{r: job["agents"][r] for r in AGENT_ROLES}, **job["agents"]["reviewers"]}
    print(f"{job['id']}: " + ", ".join(f"{name} {s['model']}/{s['effort']}" for name, s in settings.items()))


def cmd_agent(job, role):
    """Print the model and effort the orchestrator passes when it spawns `role`."""
    if role == "intake":
        setting = agent_setting("agents.intake", CONFIG.get("agents", {}).get("intake"))
    elif not job["agents"]:
        die(f"{job['id']} isn't routed yet: run factory/bin/route {job['id']}")
    elif role in AGENT_ROLES:
        setting = job["agents"][role]
    elif role.removeprefix("reviewer-") in job["agents"]["reviewers"] and role.startswith("reviewer-"):
        setting = job["agents"]["reviewers"][role.removeprefix("reviewer-")]
    else:
        die(f"{job['id']} has no agent {role!r}; routed: "
            + ", ".join([*AGENT_ROLES, *(f"reviewer-{r}" for r in job["agents"]["reviewers"])]))
    print(f"model={setting['model']} effort={setting['effort']}")
```

- [ ] **Step 7: Wire the CLI**

In the module docstring, replace:

```
  job agents <job> <json>        record the routed agent set (called by factory/bin/route)
```

with:

```
  job route <job>                ACCEPTed intake → every later agent's model and effort from config.json
  job agent <job> <role>         print model=<alias> effort=<level> for intake, spec-writer, builder, approver or reviewer-<r>
```

In `main()`, replace:

```python
        elif cmd == "agents" and len(args) == 2:
            cmd_agents(sync(resolve(args[0])), args[1])
```

with:

```python
        elif cmd == "route" and len(args) == 1:
            cmd_route(sync(resolve(args[0])))
        elif cmd == "agent" and len(args) == 2:
            cmd_agent(sync(resolve(args[0])), args[1])
```

- [ ] **Step 8: Make `bin/route` a wrapper**

Replace the whole content of `vendor/factory/factory/bin/route` with:

```python
#!/usr/bin/env python3
"""Route a job: every agent after intake gets its model and effort from config.json.

Usage: route <job-id>

A wrapper for `factory/bin/job route`, which does the work, so routing lives in
one place with the rest of the job's state.
"""

import subprocess
import sys
from pathlib import Path

JOB = Path(__file__).resolve().parent / "job"

if __name__ == "__main__":
    sys.exit(subprocess.run([str(JOB), "route", *sys.argv[1:]]).returncode)
```

- [ ] **Step 9: Update the planned-path expectations**

In `tests/test_job_planned.py`, replace:

```python
        self.assertEqual(job["agents"], {"reviewers": {"code": "sonnet", "ux": "sonnet", "ui": "haiku"}})
```

with:

```python
        self.assertEqual(job["agents"], {
            "spec-writer": {"model": "opus", "effort": "high"},
            "builder": {"model": "opus", "effort": "high"},
            "approver": {"model": "opus", "effort": "high"},
            "reviewers": {"code": {"model": "sonnet", "effort": "high"},
                          "ux": {"model": "sonnet", "effort": "medium"},
                          "ui": {"model": "haiku", "effort": "medium"}},
        })
```

and replace:

```python
        self.assertEqual(self.load()["agents"], {"reviewers": {"code": "haiku"}})
```

with:

```python
        self.assertEqual(self.load()["agents"]["reviewers"], {"code": {"model": "haiku", "effort": "medium"}})
        self.assertEqual(self.load()["agents"]["builder"], {"model": "opus", "effort": "medium"})
```

- [ ] **Step 10: Run all tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: 50 tests, all OK (33 existing + 17 new).

Also: `grep -n "cmd_agents\|\"agents\" and len" vendor/factory/factory/bin/job` prints nothing.

- [ ] **Step 11: Commit**

```bash
git add vendor/factory/factory/config.json vendor/factory/factory/bin/job vendor/factory/factory/bin/route tests/factory_project.py tests/test_job_planned.py tests/test_routing.py
git commit -m "feat: route every agent's model and effort from config.json"
```

---

### Task 2: Agents and orchestrator stop naming models

**Files:**
- Modify: all 8 files in `vendor/factory/.claude/agents/` (frontmatter line `model: …`)
- Modify: `vendor/factory/.claude/skills/factory/SKILL.md`

- [ ] **Step 1: Remove `model:` from every agent's frontmatter**

```bash
python3 - <<'EOF'
from pathlib import Path
for path in sorted(Path("vendor/factory/.claude/agents").glob("*.md")):
    head, sep, body = path.read_text().partition("\n---\n")
    lines = [l for l in head.split("\n") if not l.startswith("model:")]
    assert len(lines) == head.count("\n"), path
    path.write_text("\n".join(lines) + sep + body)
    print(path.name)
EOF
```

Expected: 8 file names. Then `grep -rn "^model:" vendor/factory/.claude/agents/` prints nothing, and `head -5 vendor/factory/.claude/agents/builder.md` still shows `---`, `name:`, `description:`, `tools:`, `hooks:`.

- [ ] **Step 2: Pipeline diagram without models**

In `SKILL.md`, replace:

```
intake (fable)     → ACCEPT (scope possibly changed) | NEEDS-INFO | REJECT, posted as an issue comment
route (script)     → reviewers + models from risk/surfaces via config.json
```

with:

```
intake             → ACCEPT (scope possibly changed) | NEEDS-INFO | REJECT, posted as an issue comment
route (script)     → every later agent's model + effort, from risk/surfaces via config.json
```

replace `spec-writer (opus) → spec.md` with `spec-writer        → spec.md`, replace `builder (opus)     → commits;` with `builder            → commits;`, and replace `approver (opus)    → APPROVE:` with `approver           → APPROVE:`.

In the Files block, replace `risk + surfaces → the job's agents` with `risk + surfaces → every agent's model and effort`.

- [ ] **Step 3: Every spawn passes model and effort**

Replace:

```
`subagent_type` set to the agent's name. Pass `model` from `job.json`
`agents` for the reviewers, and never for intake, spec-writer, builder or
approver: their frontmatter sets it. Each agent replies with one line;
```

with:

```
`subagent_type` set to the agent's name. Before every spawn, run
`factory/bin/job agent <id> <role>`, where role is `intake`, `spec-writer`,
`builder`, `approver` or `reviewer-<r>`. It prints
`model=<alias> effort=<level>`: pass both as the Agent tool's `model` and
`effort`. Agents have no model of their own, so a spawn without them silently
runs on this session's model. If the command refuses, `factory/config.json`
is wrong: stop that job and show the user the error. Each agent replies with one line;
```

Replace:

```
message**, so they run in parallel: `subagent_type` `reviewer-<r>`, model from
the same map, prompt `<header> Review round <N>.` plus the port for `ux` and
```

with:

```
message**, so they run in parallel: `subagent_type` `reviewer-<r>`, `model`
and `effort` from `factory/bin/job agent <id> reviewer-<r>`, prompt
`<header> Review round <N>.` plus the port for `ux` and
```

- [ ] **Step 4: Verify**

Run: `grep -nE "\((fable|opus|sonnet|haiku)\)|frontmatter sets" vendor/factory/.claude/skills/factory/SKILL.md; grep -c "job agent" vendor/factory/.claude/skills/factory/SKILL.md`
Expected: no lines from the first grep; the count is `2`.

- [ ] **Step 5: Commit**

```bash
git add vendor/factory/.claude/agents vendor/factory/.claude/skills/factory/SKILL.md
git commit -m "feat: agents take model and effort from config at spawn"
```

---

### Task 3: Docs say where models are set

**Files:**
- Modify: `vendor/factory/INSTALL.md`
- Modify: `README.md`

- [ ] **Step 1: INSTALL.md**

Replace `- \`claude --version\` is 2.1.257 or later (the intake agent runs on Fable).` with `- \`claude --version\` is 2.1.257 or later.`

Replace:

```
- Leave `concurrency`, `max_rounds`, `routing`, `surface_reviewers` and
  `prices_usd_per_mtok` as they are unless the user asks.
```

with:

```
- Leave `concurrency`, `max_rounds`, `model_aliases`, `effort_levels`,
  `agents`, `routing`, `surface_reviewers` and `prices_usd_per_mtok` as they
  are unless the user asks. Every agent's model and effort is set there, never
  in `.claude/agents/`.
```

Replace:

```
3. Each file in `.claude/agents/` has only these frontmatter keys: `name`,
   `description`, `tools`, `model`, and `hooks` on the builder. Claude Code
```

with:

```
3. Each file in `.claude/agents/` has only these frontmatter keys: `name`,
   `description`, `tools`, and `hooks` on the builder. No agent sets `model`:
   `factory/config.json` does, at spawn time. Claude Code
```

Replace:

```
- Intake runs on Fable, once per issue. Depending on their plan, Fable can
  bill to usage credits rather than the plan's included usage.
```

with:

```
- Each agent runs on the model and effort `factory/config.json` sets for it:
  intake in `agents`, the rest per risk in `routing` and `surface_reviewers`.
  Depending on their plan, some models bill to usage credits rather than the
  plan's included usage.
```

- [ ] **Step 2: README section**

In `README.md`, insert before the line `## Layout`:

```markdown
## Models and effort

Every agent's model and effort come from the project's `factory/config.json`;
no agent file names a model. `agents.intake` sets intake.
`routing.<low|medium|high>` sets the spec writer, builder, approver and code
reviewer for jobs of that risk, and `surface_reviewers` adds the UX, UI and
security reviewers. Models are aliases listed in `model_aliases`; efforts come
from `effort_levels`. To see what a role will run on:
`factory/bin/job agent <job> <role>`.

```

- [ ] **Step 3: Verify**

Run: `grep -n "Fable" vendor/factory/INSTALL.md README.md`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add vendor/factory/INSTALL.md README.md
git commit -m "docs: models and effort are set in config.json"
```
