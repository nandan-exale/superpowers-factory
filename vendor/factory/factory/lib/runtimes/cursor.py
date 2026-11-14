"""Cursor CLI: `cursor-agent -p --output-format json <prompt>`, one JSON result with token usage, no cost."""

import json

from runtimes import base_env, prepend_system

NAME = "cursor"
BINARY = "cursor-agent"
NPM_PACKAGE = None   # installs only through Cursor's shell script; the Actions workflow refuses it
# Effort is part of Cursor's model names (claude-opus-5-5-high, gpt-5.5-low, ...), so efforts stays [].
CAPS = {"resume": True, "reports_cost": False, "reports_tokens": True, "efforts": [], "stop_hook": False,
        "silent_new_session": False}


def build(run):
    prepend_system(run)
    argv = ["cursor-agent", "-p", "--output-format", "json", "--model", run["model"], "--force"]
    if run.get("resume"):
        argv += ["--resume", run["resume"]]
    return [*argv, run["prompt_path"].read_text()], base_env(run)


def parse(stdout):
    for line in reversed(stdout.strip().splitlines()):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            u = data.get("usage")
            usage = None if not isinstance(u, dict) else {
                "input_tokens": u.get("inputTokens", 0),
                "output_tokens": u.get("outputTokens", 0),
                "cache_read_input_tokens": u.get("cacheReadTokens", 0)}
            return {"session_id": data.get("session_id"), "model": None, "usage": usage, "cost_usd": None,
                    "cost_source": None, "cost_by_model": {}, "error": bool(data.get("is_error"))}
    raise ValueError("no result object in cursor-agent's output")
