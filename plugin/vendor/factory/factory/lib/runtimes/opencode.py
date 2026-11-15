"""OpenCode: `opencode run --format json <message>`, JSON-lines events, cost reported per step."""

import json

from runtimes import base_env, prepend_system

NAME = "opencode"
BINARY = "opencode"
NPM_PACKAGE = "opencode-ai"
# --session <id> creates a session that doesn't exist, so a lost session is no error (recorded fixture README).
CAPS = {"resume": True, "reports_cost": True, "reports_tokens": True, "efforts": [], "stop_hook": False,
        "silent_new_session": True}
# Agents must not prompt; they may edit and run commands; the read-only rule is checked after the run.
PERMISSION = {"edit": "allow", "bash": "allow", "webfetch": "deny", "external_directory": "allow"}


def build(run):
    prepend_system(run)
    argv = ["opencode", "run", "--format", "json", "-m", run["model"]]
    if run.get("resume"):
        argv += ["--session", run["resume"]]
    env = {**base_env(run), "OPENCODE_CONFIG_CONTENT": json.dumps({"permission": PERMISSION})}
    return [*argv, run["prompt_path"].read_text()], env


def parse(stdout):
    evs = []
    for line in stdout.splitlines():
        try:
            evs.append(json.loads(line))
        except ValueError:
            continue
    evs = [e for e in evs if isinstance(e, dict)]
    if not evs:
        raise ValueError("no JSON events in opencode's output")
    session = next((e.get("sessionID") for e in evs if e.get("sessionID")), None)
    cost, usage, steps = 0.0, {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}, 0
    for e in evs:
        part = e.get("part") or {}
        if e.get("type") == "step_finish" or part.get("type") == "step-finish":
            steps += 1
            cost += float(part.get("cost") or 0.0)
            t = part.get("tokens") or {}
            usage["input_tokens"] += t.get("input", 0)
            usage["output_tokens"] += t.get("output", 0) + t.get("reasoning", 0)
            usage["cache_read_input_tokens"] += (t.get("cache") or {}).get("read", 0)
    error = any(e.get("type") == "error" for e in evs) or not steps
    return {"session_id": session, "model": None, "usage": usage if steps else None,
            "cost_usd": round(cost, 6) if steps else None, "cost_source": "cli" if steps else None,
            "cost_by_model": {}, "error": error, "limit": None}
