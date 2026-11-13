# Phase 2: prove it — Design

Date: 2026-11-13
Status: approved design. Phase 2 of 5 (see `2026-11-13-roadmap.md`).

## Goal

Exercise, with real agents on a real GitHub repo, the paths that so far have
only been tested with fakes: tagged findings, budget stops, the learning loop
and the headless runner. And catch regressions when an agent prompt changes.

Both tools spend real money, so both are run by hand, never in CI, under a
hard spend cap.

## Decisions

| Question | Decision |
|---|---|
| How scenarios run | Real agents on a disposable sandbox repo (factory-e2e), started by hand. |
| Spend control | A `--max-usd` cap, enforced twice: the sandbox's own `budgets.daily_usd` is set to it, and the harness stops between steps once it's reached. |
| Prompt evals | Real `claude -p` runs of one agent prompt against fixture inputs, several samples each, compared with a committed baseline. |
| Where the tools live | Plugin repo, `scripts/` (maintainer tools; not installed into projects). |

## Components

### 1. `scripts/e2e` — scenario runner

```
scripts/e2e --sandbox <path to a local clone of the sandbox repo> --max-usd 10 [--only <scenario>] [--keep]
```

Preconditions it checks, refusing otherwise:
- the sandbox clone's `origin` is on github.com and **is not this plugin's
  repo**; its name must contain `e2e` or `sandbox` (a guard against pointing
  it at a real project);
- the factory is installed there and `factory/bin/doctor` exits 0;
- `gh auth status` succeeds and the working tree is clean.

Each scenario is a directory `tests/e2e/<name>/` with:
- `scenario.json`: `{"title", "issue_body", "labels", "config_patch",
  "expect": {...}, "timeout_minutes"}`;
- optional `setup.py` that prepares the sandbox (for example seeding job
  folders for the learning scenario).

Per scenario the harness:
1. applies `config_patch` to the sandbox's `factory/config.json` (deep
   merge), with `budgets.daily_usd` forced to the remaining cap, commits
   `chore(e2e): <scenario> config` on the sandbox `main` and pushes;
2. runs `setup.py` if present;
3. files the issue with `gh issue create` and the given labels;
4. drives the factory: `claude -p "/factory run" --output-format json
   --permission-mode dontAsk --settings factory/runner-settings.json` in the
   sandbox (same flags and env scrubbing as the runner), repeating until the
   job reaches a terminal or `needs-human` stage or `timeout_minutes` passes;
5. checks `expect` against the job folder and GitHub (see below);
6. writes `e2e-results/<timestamp>/<scenario>.md` with the outcome, the
   job's spend and the evidence paths;
7. unless `--keep`, closes the issue and PR it created and deletes the job
   branch (only artifacts whose numbers it recorded in step 3–4).

`expect` keys (all optional): `stage` (final stage or list of allowed
stages), `stage_not`, `decision_prefix` (first line of
`decision.md`), `budget_stopped` (`job.json` records a budget stop), `review_tags_valid` (every
finding in every review parses with a valid tag), `min_findings`,
`issue_labels`, `pr_state`, `files` (globs under the sandbox's `factory/jobs/`,
`{job}` = the job id, each must match), `first_lines` (`{glob: prefix}`),
`stdout_contains` (in the factory run's output), `learning_issue` (a
`factory:learning` issue was filed), `runner_log_contains`.

Scenarios shipped:

| Scenario | Set-up | Expect |
|---|---|---|
| `happy-path` | small, clear issue ("add a `--version` flag") | `stage: merged`, valid review tags |
| `tagged-finding` | issue that asks for code but says "no tests needed" | `min_findings: 1`, `review_tags_valid`, a `missing-test` or `other:*` tag |
| `budget-stop` | `config_patch.budgets.job_usd: 0.05` | `stage: needs-human`, `budget_stopped: true` |
| `needs-info` | ambiguous one-line issue | `stage: needs-info`, `issue_labels` has `factory:needs-info` |
| `learning` | `setup.py` seeds 3 finished job folders with the same tag; `learning.threshold: 3` | `factory:learning` issue filed, `proposal.md` first line `PROPOSAL:` |
| `runner-tick` | requires the Keychain token; runs `factory/bin/runner tick` once instead of step 4 | `runner.log` shows a run, job leaves `intake` |

Spend: after each scenario the harness sums the sandbox's
`factory/jobs/**/log.jsonl` cost lines since it started; when the total
reaches `--max-usd` it stops before the next scenario and says so.

Exit 0 only if every scenario run met its `expect`.

### 2. `scripts/eval` — agent prompt evals

```
scripts/eval [--agent intake|reviewer-code|...] [--samples 3] [--max-usd 5] [--update-baseline]
```

Fixtures live in `tests/evals/<agent>/<case>/`:
- `input.md`: the user prompt the orchestrator would send (job header and
  the material, for example an issue body or a diff);
- `files/`: a tiny repo snapshot the agent may read (copied to a temp dir
  that becomes the cwd);
- `expect.json`: `{"first_line": "DECISION: REJECT"}` or
  `{"verdict": "CHANGES", "tags_any": ["missing-test"]}` or
  `{"regex": "..."}`.

For each case and sample, it runs
`claude -p --output-format json --permission-mode dontAsk
--append-system-prompt <agent body> --model <model> --effort <effort>`
with the model and effort from `vendor/factory/factory/config.json` for that
role (medium risk), tools limited to the agent's `tools` frontmatter, and
writes go to the temp dir only. It parses the output file the agent writes
(or stdout), checks `expect`, and records pass/fail and `total_cost_usd`.

Report: per case, pass rate over samples; per agent, mean pass rate and cost.
`tests/evals/baseline.json` holds the last accepted pass rates. A case fails
the run when its pass rate is below its baseline by more than one sample.
`--update-baseline` writes the new rates (a human reviews that diff).

Initial cases (2–4 per agent): intake accept / reject / needs-info;
reviewer-code finds a planted off-by-one and tags it, passes a clean diff,
flags a deleted test as `weakened-test`; reviewer-security flags a
hard-coded key (a fake `sk-test-` string) as `secrets`; approver escalates
when reviews disagree; learner returns `PROPOSAL: NONE` for unfixable
evidence.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| e2e | sandbox guard fails | exit 2 before any spend |
| e2e | scenario timeout | scenario fails, cleanup still runs |
| e2e | cap reached | remaining scenarios skipped, listed as such, exit 1 |
| eval | `claude` missing or not logged in | exit 2 with the fix |
| eval | cap reached | stop, report partial results, exit 1 |

## Testing

The harnesses themselves get stdlib unit tests with `claude` and `gh`
faked on `PATH`: sandbox guard, config patch merge, `expect` matching,
spend summing and cap stop, eval expectation parsing, baseline comparison.
No unit test spends money.

## Out of scope

- Running either tool in CI.
- Creating the sandbox repo (the user makes it once; README says how).
- Scoring free-text quality beyond first lines, verdicts, tags and regexes.
