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
