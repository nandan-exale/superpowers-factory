"""Agent CLI adapters, one module per runtime. An adapter is the only code that knows its CLI.

Every adapter has:
  NAME          its config name
  BINARY        the CLI it starts; orchestrate refuses to run when it isn't on PATH
  NPM_PACKAGE   the npm package that installs BINARY, or None when npm can't
  CAPS          {"resume": bool, "reports_cost": bool, "reports_tokens": bool, "efforts": [...]}
  build(run)    -> (argv, env). `run` is the dict orchestrator.loop builds: repo, job_id, role,
                   access, model, effort, system_path, prompt_path, settings_dir, stem, resume,
                   session_id. The prompt goes to the process on stdin; an adapter may rewrite
                   prompt_path before the loop opens it.
  parse(stdout) -> {"session_id", "model", "usage", "cost_usd", "cost_source", "cost_by_model",
                   "error"}; ValueError when stdout has no result.
"""

import importlib

NAMES = ("claude", "codex", "opencode", "copilot", "cursor")


def load(name):
    if name not in NAMES:
        raise ValueError(f"unknown runtime {name!r}; known: {', '.join(NAMES)}")
    return importlib.import_module(f"runtimes.{name}")


def prepend_system(run):
    """Put the agent's instructions in front of the task, for CLIs with no system-prompt option."""
    system = run["system_path"].read_text()
    task = run["prompt_path"].read_text()
    run["prompt_path"].write_text(f"{system}\n\n---\n\n# Your task\n\n{task}")


def base_env(run):
    return {"FACTORY_RUNNER": "1", "FACTORY_JOB": run["job_id"]}


def writable_dirs(run):
    """What a non-Claude agent may write: the job folder, and the main checkout's .git (worktree commits
    and `job push` write objects and refs there). Its cwd is writable too."""
    return [run["settings_dir"].parent, run["repo"] / ".git"]
