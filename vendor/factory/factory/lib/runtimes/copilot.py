"""GitHub Copilot CLI: `copilot -p <prompt> --output-format json`, JSON-lines events; auth from gh / GH_TOKEN.
Reports no cost."""

import json

from runtimes import base_env, prepend_system

NAME = "copilot"
BINARY = "copilot"
NPM_PACKAGE = "@github/copilot"
CAPS = {"resume": True, "reports_cost": False, "reports_tokens": False, "efforts": [], "stop_hook": False,
        "silent_new_session": False}
DENIED = ("shell(git push " "--force)", "shell(git push -f)", "shell(gh repo delete)", "shell(gh repo edit)")


def build(run):
    prepend_system(run)
    argv = ["copilot", "-p", run["prompt_path"].read_text(), "--output-format", "json",
            "--model", run["model"], "--allow-all-tools"]
    for rule in DENIED:
        argv += ["--deny-tool", rule]
    if run.get("resume"):
        argv += ["--resume", run["resume"]]
    return argv, base_env(run)


def parse(stdout):
    evs = []
    for line in stdout.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            evs.append(data)
    if not evs:
        raise ValueError("no JSON events in copilot's output")
    session = next(((e.get("data") or {}).get("sessionId") for e in evs if e.get("type") == "session.start"), None)
    error = (not any(e.get("type") == "result" for e in evs)
             or any(str(e.get("type", "")).endswith("error") for e in evs))
    return {"session_id": session, "model": None, "usage": None, "cost_usd": None, "cost_source": None,
            "cost_by_model": {}, "error": error}
