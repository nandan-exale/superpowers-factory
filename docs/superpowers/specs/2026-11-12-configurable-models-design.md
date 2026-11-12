# Configurable models and effort — Design

Date: 2026-11-12
Status: approved design

## Goal

No model or effort level is fixed in code or prompts. `factory/config.json`
sets the model and the effort for every factory agent; agent files carry no
`model:`; the orchestrator passes both on every spawn.

## Decisions

| Question | Decision |
|---|---|
| How models are named | Aliases (`fable`, `opus`, `sonnet`, `haiku`), passed as the Agent tool's `model` at spawn time. The tool only accepts aliases, so exact version IDs can't be pinned. |
| What varies with risk | Every agent after intake: spec-writer, builder, approver and the code reviewer, per `low`/`medium`/`high`. Surface reviewers (`ui`, `security`) stay add-ons. Intake runs before risk is known, so it has one setting. |
| Allowed values | Lists in config (`model_aliases`, `effort_levels`), so code holds no model name. |

## Config

```json
"model_aliases": ["fable", "opus", "sonnet", "haiku"],
"effort_levels": ["low", "medium", "high", "xhigh", "max"],
"agents": { "intake": { "model": "fable", "effort": "high" } },
"routing": {
  "low":    { "spec-writer": {"model": "opus", "effort": "medium"}, "builder": {"model": "opus", "effort": "medium"},
              "approver": {"model": "opus", "effort": "medium"}, "code": {"model": "haiku", "effort": "medium"} },
  "medium": { "spec-writer": {"model": "opus", "effort": "high"}, "builder": {"model": "opus", "effort": "high"},
              "approver": {"model": "opus", "effort": "high"}, "code": {"model": "sonnet", "effort": "high"} },
  "high":   { "spec-writer": {"model": "opus", "effort": "high"}, "builder": {"model": "opus", "effort": "high"},
              "approver": {"model": "opus", "effort": "high"}, "code": {"model": "sonnet", "effort": "high"} }
},
"surface_reviewers": {
  "ui":       { "ux": {"model": "sonnet", "effort": "medium"}, "ui": {"model": "haiku", "effort": "medium"} },
  "security": { "security": {"model": "opus", "effort": "high"} }
}
```

Defaults keep the upstream models. In a `routing.<risk>` table, `spec-writer`,
`builder` and `approver` are agents; every other key is a reviewer, and `code`
is required.

## Scripts

- `job route <id>`: for an intake job whose intake.md says ACCEPT, computes the
  agent set from its risk and surfaces and stores it in `job.json` `agents`:
  `{"spec-writer": {model, effort}, "builder": {...}, "approver": {...},
  "reviewers": {"code": {...}, "ux": {...}}}`. The dashboard keeps working: it
  reads only the keys of `agents.reviewers`.
- `factory/bin/route <id>` stays as a wrapper that runs `job route <id>`, so the
  orchestrator's call is unchanged. `job agents` (the old setter) is removed.
- `job planned` uses the same in-process function.
- `job agent <id> <role>` prints `model=<alias> effort=<level>`. Role is
  `intake` (from `agents.intake`), `spec-writer`, `builder`, `approver`, or
  `reviewer-<r>` (from `job.json`).
- Validation refuses with a message naming the config key: an unknown risk or
  surface, a routing table missing a required role, a setting that isn't
  exactly `{model, effort}`, a model not in `model_aliases`, an effort not in
  `effort_levels`.

## Prompts and docs

- `model:` removed from all eight agent files.
- Orchestrator skill: the pipeline diagram names no models; every spawn first
  runs `factory/bin/job agent <id> <role>` and passes both values; a refusal
  stops the job and is shown to the user.
- INSTALL.md (vendored), factory-install and README: no Fable wording; agent
  frontmatter has no `model` key; the new config sections are explained.

## Testing

Stdlib `unittest`, using the existing `FactoryProject` helper:

- routing for each risk, with and without surfaces;
- each validation failure;
- `job agent` for intake, an agent and a reviewer, and before routing;
- `job route` refusing a non-ACCEPT job;
- the `bin/route` wrapper end to end;
- the planned-path tests updated to the new `agents` shape.
