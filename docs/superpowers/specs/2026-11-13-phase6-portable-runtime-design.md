# Phase 6: portable runtime — Design

Date: 2026-11-13
Status: draft for review. Phase 6 (see `2026-11-13-roadmap.md`), built after 5c.
Two parts, each its own plan and PR-sized change: 6a script orchestrator with
the Claude Code adapter (no behaviour change), 6b the Codex, OpenCode, Copilot
CLI and Cursor CLI adapters, model tiers, run caps and install from any agent.

## Goal

The factory runs under any of five coding agent CLIs, Claude Code, OpenAI Codex
CLI, OpenCode, GitHub Copilot CLI and Cursor CLI, chosen by one config key.
Today it needs Claude Code at five points:

1. The orchestrator is an LLM session: the `factory` skill spawns agents with
   the Agent tool (`subagent_type`) and resumes the builder with `SendMessage`.
2. Agents are `.claude/agents/*.md`; models and efforts are Claude aliases.
3. Cost and budgets come from Claude Code subagent transcripts
   (`~/.claude/projects/*/subagents/agent-*.jsonl`, matched by `Job folder:`).
4. Hooks: the plugin's SessionStart hook (`${CLAUDE_PLUGIN_ROOT}`) and the
   installed Stop hook in `.claude/settings.json`.
5. `runner tick` launches `claude` with `/factory run` and a Claude token.

`job`, `gate` and `route` are already plain Python and stay as they are.

## Decisions

| Question | Decision |
|---|---|
| Agents supported | Claude Code (must keep working), Codex CLI, OpenCode, Copilot CLI, Cursor CLI. |
| Mixing agents | One runtime per run, set by `runtime` in `config.json`. No per-role mixing. |
| Orchestration | A stdlib script, `factory/bin/orchestrate`, replaces the LLM orchestrator. Agents run as headless CLI child processes through one adapter per CLI. |
| Models | Routing names tiers (`fast`, `balanced`, `strong`, `frontier`); each runtime maps tiers to its models. |
| Cost | Recorded per agent run from the CLI's own output. Where a CLI reports neither cost nor tokens, cost is `null`. |
| Budgets without cost | `job_hours` plus new run-count caps `budgets.job_runs` and `budgets.daily_runs`. |
| Order | After 5c. Phases 3–5c are not revised; this phase adapts what they add (digest, report, pause, Linux and Actions runners). |

## Architecture

```
factory/bin/orchestrate ──calls──▶ factory/bin/job | gate | route   (job stays the only writer of job.json)
        │
        └─spawns──▶ factory/lib/runtimes/<runtime>.py ──▶ claude -p | codex exec | opencode run | copilot -p | cursor-agent -p
                         │                                (cwd = job worktree, prompt = agents/<role>.md + header)
                         └─job record-run──▶ factory/jobs/<id>/runs/<seq>-<role>.json  (+ .log)
```

## Components

### 1. `factory/bin/orchestrate` (vendored, new; 6a)

Commands: `orchestrate run` (drain the queue), `orchestrate run <n>` (one
issue), `orchestrate step <id>` (advance one job by one step, for debugging).

It carries out the pipeline the `factory` skill describes today, as code:
`job queue` → start `new`/`resume` lines → intake (or `job planned` for
`factory:planned`) → `route` → spec → build → gate → reviewers in parallel,
wait for all → approver → `job merge` or `needs-human`; resume rules per
stage; budgets; pause (phase 4); the learning pass; `job summary` at the end.
Every state change goes through `job` subcommands run as subprocesses. The
transition table lives in one function so it reads like today's skill text.

- Agents start with `subprocess.Popen`, up to `concurrency` jobs at once.
  cwd is the job's worktree, or the main checkout for intake and learner.
  stdout and stderr go to `runs/<seq>-<role>.log`.
- The loop waits on children; when one exits it calls the adapter's `parse`,
  runs `job record-run`, reads the agent's first line from its file
  (`build.md`, `review-<r>.md`, `decision.md`, …) and applies the transition.
- Prompts are built exactly as now: the `<header>` line (keeping
  `Job folder: <path>/`), plus the step's instruction text from the skill.
  Issue text never enters a prompt.
- On SIGTERM it terminates its children and exits non-zero; state is in
  files, so the next run resumes.
- Output: one line per transition, as the skill reports today, then the
  summary.

### 2. Runtime adapters, `factory/lib/runtimes/` (vendored, new)

One module per CLI: `claude.py` (6a); `codex.py`, `opencode.py`,
`copilot.py`, `cursor.py` (6b). Each is the only code that knows its CLI's
flags and output format, about 100 lines, stdlib only:

```python
CAPS = {"resume": bool, "reports_cost": bool, "reports_tokens": bool,
        "efforts": [...], "read_only": "sandbox" | "tools" | None}

def build(prompt, model, effort, cwd, access, resume=None) -> (argv, env)
def parse(stdout) -> {"session_id", "model", "usage": {...} | None,
                      "cost_usd": float | None, "final": str}
```

- Every adapter runs its CLI non-interactively with structured output
  (JSON or JSON lines) and with approvals off for the job's worktree only.
- `access: read` uses the CLI's read-only sandbox or tool allowlist where it
  has one (`CAPS["read_only"]`). This is defence in depth; the guarantee is the
  post-run check in §5.
- The exact flags and output fields for each CLI are checked against that
  CLI's `--help` and a recorded real run while writing the plan, and frozen as
  test fixtures. `doctor` checks the selected CLI is on `PATH`, prints a
  version, and is logged in.

### 3. Neutral agent prompts, `factory/agents/<role>.md` (vendored; 6a)

`vendor/factory/.claude/agents/*.md` move to `vendor/factory/factory/agents/`.
Bodies stay the same apart from tool names. Frontmatter keeps `name`,
`description` and a new `access: read | write` (`builder`, `learner`: write;
everyone else: read, plus their own file in the job folder). `tools:` goes,
because tool names differ per CLI. The adapter delivers the prompt as its CLI
allows: `--append-system-prompt` (or equivalent) where supported, else
prepended to the task prompt.

The builder's "load these Superpowers skills with the Skill tool" becomes "use
these Superpowers skills if your agent has them". The learner gets the same
treatment. `factory:planned` jobs still work without Superpowers, because the
plan carries the steps.

The installed `.claude/agents/` copies are removed by `/factory-update`;
nothing spawns them any more.

### 4. Config: runtime and tiers (vendored `config.json`, `job`; 6b)

```json
"runtime": "claude",
"runtimes": {
  "claude": {
    "tiers": {"fast": "haiku", "balanced": "sonnet", "strong": "opus", "frontier": "fable"},
    "efforts": ["low", "medium", "high", "xhigh", "max"],
    "credential_env": "CLAUDE_CODE_OAUTH_TOKEN",
    "prices_usd_per_mtok": { "claude-opus-5-5": {…}, … }
  },
  "codex":    { "tiers": {…}, "efforts": [...], "credential_env": "OPENAI_API_KEY", "prices_usd_per_mtok": {…} },
  "opencode": { "tiers": {…}, "efforts": [...], "credential_env": "<provider's key variable, chosen at install>", "prices_usd_per_mtok": {…} },
  "copilot":  { "tiers": {…}, "efforts": [...] },
  "cursor":   { "tiers": {…}, "efforts": [...], "credential_env": "CURSOR_API_KEY" }
}
```

- `agents`, `routing` and `surface_reviewers` name `{"tier", "effort"}`
  instead of `{"model", "effort"}`. `model_aliases`, `effort_levels` and the
  top-level `prices_usd_per_mtok` move under `runtimes.claude`.
- `job agent <id> <role>` prints `runtime=<r> model=<model> effort=<level>`:
  role → tier → that runtime's model. An effort the runtime lacks becomes the
  nearest lower supported level (or the lowest, if none is lower), and the
  substitution is recorded in the run file. A tier missing for the runtime
  makes `job agent` refuse, naming the key to add.
- In 6a, `runtime` is fixed to `claude` and routing keeps model aliases;
  tiers arrive in 6b.
- `/factory-update` migrates an installed config: `haiku→fast`,
  `sonnet→balanced`, `opus→strong`, `fable→frontier`, moves the Claude keys
  under `runtimes.claude`, and shows the diff like every other change.

### 5. Runs, cost and budgets (vendored `job`; 6a, run caps in 6b)

- New `job record-run <id> <role>` reads the adapter's parsed result as JSON
  on stdin and writes `runs/<seq>-<role>.json`:
  `{seq, role, runtime, model, effort, session_id, started, ended, exit,
  usage, cost_usd, cost_source: "cli" | "tokens" | null, notes}`.
  `cost_usd` is the CLI's reported cost, else tokens × the runtime's prices,
  else `null`.
- New `job set-session <id> builder <session_id>` stores the builder's
  session id in `job.json`.
- `job.json` `cost_usd` becomes the sum of the job's run files; `job costs`
  groups them by model. The transcript scan (`cost_for_needle`) and the
  learner's `Job folder:` cost matching are removed; the learner's runs go to
  `jobs/learning/<tag-dir>/runs/`.
- Budgets: `job_usd` and `daily_usd` count only known costs. When the runtime's
  `CAPS` say it reports neither cost nor tokens, `budgets.job_runs` and
  `budgets.daily_runs` apply instead (agent processes per job, per 24 h);
  `job_hours` applies everywhere. Hitting any cap prints the same
  `BUDGET: <id> → needs-human (<reason>)` line.
- `job summary`, `job report`, the digest and the dashboard show
  `n/a (<k> runs)` where cost is unknown.

**Read-only check.** Before an `access: read` agent starts, the orchestrator
records the worktree's HEAD and `git status --porcelain` and the job folder's
file list. After it exits: HEAD and status must be unchanged, and the only new
or changed file in the job folder must be that role's own file. A violation
discards the run (the file is moved to `runs/<seq>-<role>.rejected`) and sends
the job to `needs-human` with the diff, through `job escalate`.

### 6. Builder resume (vendored `orchestrate`, `job`; 6a)

The builder's `session_id` from its first run is stored with
`job set-session`. Each later round resumes it through the adapter's
`resume=`. When the runtime can't resume (`CAPS["resume"]` false), or the
resume fails because the session is gone, the orchestrator spawns a fresh
builder with today's "you are resuming" instruction (it reads `build.md`,
`git log` and the plan's ticked tasks).

### 7. The `/factory` skill (vendored; 6a)

`/factory run` and `/factory run <n>` become: run `factory/bin/orchestrate
run [<n>]` in the background and report its lines; don't spawn agents
yourself. `/factory <anything>` (questions, feedback, reject, needs-info
answers, new features) keeps its current text, which already only calls the
scripts. The skill works in any agent that loads `SKILL.md` files.

### 8. Runner (vendored `runner`, workflow; 6a, credentials in 6b)

- `runner tick` runs `factory/bin/orchestrate run` instead of
  `claude -p "/factory run"`, keeping the lock, preflight, pull, `max_minutes`
  timeout (SIGTERM to `orchestrate`), and run logs.
- The credential comes from the 5b/5c sources (Keychain, `secret-tool`, 0600
  file, Actions secret), stored under the runtime's name and exported only as
  `runtimes.<runtime>.credential_env` in the child environment. Copilot uses
  the existing `gh` auth and needs none.
- The stripped-variables list becomes per runtime: every other runtime's
  `credential_env` plus today's `ANTHROPIC_*` list when the runtime isn't
  `claude`.
- The Actions workflow passes the secret named by the runtime's
  `credential_env`.

### 9. Install from any agent (plugin skills; 6b)

- The plugin's skills (`factory-install`, `factory-handoff`, `factory-update`,
  `factory-uninstall`) already use the `SKILL.md` layout, so
  `npx skills add <owner>/superpowers-factory` installs them for any agent.
  They lose Claude-only wording and refer to `${CLAUDE_PLUGIN_ROOT}` only on
  Claude Code; elsewhere they find the vendored files next to their own
  `SKILL.md`.
- `/factory-install` asks which runtime to use and writes `runtime`, adds the
  factory section to `AGENTS.md` (read by Codex, OpenCode, Copilot and
  Cursor) as it does to `CLAUDE.md` today, and installs the Stop hook only when
  the runtime is `claude`. The gate enforces `checks.sh` on every runtime.
- The SessionStart hook stays a Claude Code convenience; nothing depends on it.
- README gets a short "Using another agent" section.

### 10. Doctor (vendored `doctor`)

- 6a: checks `factory/agents/` is complete and `orchestrate` runs.
- 6b: the selected runtime's CLI is on `PATH` and logged in; its `tiers` cover
  every tier routing uses; its `credential_env` is set or obtainable when the
  runner is installed; WARN when Superpowers isn't installed for that agent;
  WARN when cost is unknown and `job_runs`/`daily_runs` aren't set.

## Error handling

| Case | Result |
|---|---|
| Selected CLI missing or not logged in | `doctor` FAIL; `orchestrate` refuses before starting any job |
| Agent exits non-zero, or its output can't be parsed | retry the run once; then the job goes to `needs-human` with the last 40 lines of its log |
| Agent's file or first line missing or invalid | resume (or respawn) once with the refusal, then `job escalate`, as today |
| Resume session gone, or runtime can't resume | fresh builder told it is resuming |
| Effort not supported by the runtime | nearest lower supported level; noted in the run file |
| Read-only role changed the worktree or another file | run discarded, job to `needs-human` with the diff |
| Cost unknown | run caps apply; cost shown as `n/a (<k> runs)` |
| Tier missing for the runtime | `job agent` refuses naming the key; that job stops, others continue |
| `orchestrate` gets SIGTERM | children terminated; next run resumes from files |

## Testing

- Adapter tests (stdlib `unittest`): for each runtime, `build` against
  expected argv/env for write and read access, with and without resume;
  `parse` against output fixtures recorded once from the real CLI and
  committed under `tests/fixtures/runtimes/<runtime>/`.
- Fake CLIs: one stdlib script per runtime, put on `PATH` in tests, that
  replays a fixture and writes the role's file into the job folder.
- `orchestrate` tests on `tests/factory_project.py` with the fake runtime:
  full happy path to `merged`; `factory:planned`; gate FAIL → rebuild;
  CHANGES → rebuild; parallel reviewers wait for all; resume fallback;
  `job_usd` and `job_runs` caps; daily caps; read-only violation; SIGTERM then
  resume; pause from phase 4.
- `job record-run`, `set-session`, cost sum and `job agent` tier resolution
  get unit tests; `/factory-update` config migration gets a test with a
  pre-phase-6 config.
- `scripts/e2e --runtime <name>` and `scripts/eval --runtime <name>` run the
  existing scenarios and evals on a real CLI. They spend money and run by hand.
- 6a must pass the existing e2e scenarios on Claude with the same outcomes as
  before, which is its "no behaviour change" proof.

## Out of scope

- Mixing runtimes per role in one run.
- Windows.
- An MCP layer.
- Estimating cost for CLIs that don't report it.
- Changing Superpowers itself, or installing it for other agents.
