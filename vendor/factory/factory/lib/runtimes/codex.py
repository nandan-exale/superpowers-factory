"""Codex CLI: `codex exec --json`, prompt on stdin (`-`), JSON-lines events on stdout."""

import json

from runtimes import base_env, prepend_system, writable_dirs

NAME = "codex"
BINARY = "codex"
NPM_PACKAGE = "@openai/codex"
CAPS = {"resume": True, "reports_cost": False, "reports_tokens": True, "efforts": ["low", "medium", "high"],
        "stop_hook": False, "silent_new_session": False}


def build(run):
    prepend_system(run)
    head = ["codex", "exec", "resume", run["resume"]] if run.get("resume") else ["codex", "exec"]
    # `codex exec resume` takes no --sandbox or --add-dir (recorded help.txt); -c overrides work for both.
    roots = json.dumps([str(d) for d in writable_dirs(run)])
    argv = [*head, "--json", "--skip-git-repo-check", "-m", run["model"],
            "-c", 'sandbox_mode="workspace-write"',
            "-c", f"sandbox_workspace_write.writable_roots={roots}",
            "-c", "sandbox_workspace_write.network_access=true"]
    if run["effort"] != "none":
        argv += ["-c", f'model_reasoning_effort="{run["effort"]}"']
    return [*argv, "-"], base_env(run)


def events(stdout):
    out = []
    for line in stdout.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            out.append(data)
    if not out:
        raise ValueError("no JSON events in codex's output")
    return out


def parse(stdout):
    evs = events(stdout)
    session = next((e.get("thread_id") for e in evs if e.get("type") == "thread.started"), None)
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
    turns = 0
    for e in evs:
        if e.get("type") == "turn.completed":
            u = e.get("usage") or {}
            turns += 1
            cached = u.get("cached_input_tokens", 0)   # part of input_tokens, not on top of it
            usage["input_tokens"] += u.get("input_tokens", 0) - cached
            usage["output_tokens"] += u.get("output_tokens", 0)
            usage["cache_read_input_tokens"] += cached
    error = any(e.get("type") in ("turn.failed", "error") for e in evs) or not turns
    return {"session_id": session, "model": None, "usage": usage if turns else None, "cost_usd": None,
            "cost_source": None, "cost_by_model": {}, "error": error}
