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
                   "error", "limit"}; ValueError when stdout has no result. `limit` is None, or
                   {"message", "until"} when the run hit a usage limit (`until`: aware UTC datetime
                   or None); orchestrator.loop then waits for the reset instead of escalating.
"""

import importlib

NAMES = ("claude", "codex", "opencode", "copilot", "cursor")
# Every agent CLI credential the factory knows. orchestrate hands these only to agents; job, gate, gh,
# git and checks.sh never see them.
CREDENTIAL_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                   "OPENAI_API_KEY", "CODEX_API_KEY", "CURSOR_API_KEY")
CLAUDE_VARS = CREDENTIAL_VARS[:4]  # what Claude Code reads, whatever runtimes.claude says


def load(name):
    if name not in NAMES:
        raise ValueError(f"unknown runtime {name!r}; known: {', '.join(NAMES)}")
    return importlib.import_module(f"runtimes.{name}")


def credential_vars(cfg):
    """CREDENTIAL_VARS plus every runtimes.<r>.credential_env in config (OpenCode's provider key, say)."""
    extra = [c.get("credential_env") for c in (cfg.get("runtimes") or {}).values() if isinstance(c, dict)]
    return tuple(dict.fromkeys([*CREDENTIAL_VARS, *(e for e in extra if e)]))


def agent_vars(name, cfg):
    """The credentials an agent of runtime `name` gets: its credential_env, plus the Anthropic ones for claude."""
    own = ((cfg.get("runtimes") or {}).get(name) or {}).get("credential_env")
    return ((own,) if own else ()) + (CLAUDE_VARS if name == "claude" else ())


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
