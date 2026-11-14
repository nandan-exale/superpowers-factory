"""Claude Code: one `claude -p` process per agent run, prompt on stdin, one JSON result on stdout."""

import json

NAME = "claude"
CAPS = {"resume": True, "reports_cost": True, "reports_tokens": True,
        "efforts": ["low", "medium", "high", "xhigh", "max"]}

# The tools each agent had as a Claude Code subagent (its old `tools:` frontmatter).
TOOLS = {
    "intake": "Read,Grep,Glob,Write",
    "spec-writer": "Read,Grep,Glob,Bash,Write",
    "builder": "Read,Grep,Glob,Bash,Edit,Write,Skill",
    "approver": "Read,Grep,Glob,Bash,Write",
    "learner": "Read,Grep,Glob,Write,Skill",
}
REVIEWER_TOOLS = "Read,Grep,Glob,Bash,Write"


def tools(role):
    return REVIEWER_TOOLS if role.startswith("reviewer-") else TOOLS[role]


def settings(repo, role):
    """runner-settings.json for every agent; the builder also gets the gate's Stop hook, which sends
    it back to work while checks.sh fails (it was a hook in the builder's subagent frontmatter)."""
    data = json.loads((repo / "factory" / "runner-settings.json").read_text())
    if role != "builder":
        return data
    hook = {"type": "command", "command": f'"{repo}/factory/bin/gate" --hook'}
    hooks = dict(data.get("hooks") or {})
    hooks["Stop"] = [*hooks.get("Stop", []), {"hooks": [hook]}]
    return {**data, "hooks": hooks}


def build(run):
    path = run["settings_dir"] / f"{run['stem']}.settings.json"
    path.write_text(json.dumps(settings(run["repo"], run["role"]), indent=2) + "\n")
    argv = ["claude", "-p", "--output-format", "json", "--model", run["model"], "--effort", run["effort"],
            "--append-system-prompt-file", str(run["system_path"]), "--tools", tools(run["role"]),
            "--settings", str(path), "--permission-mode", "dontAsk"]
    if run.get("resume"):
        argv += ["--resume", run["resume"]]
    elif run.get("session_id"):
        argv += ["--session-id", run["session_id"]]
    # SCRUB keeps the token out of hooks and tests claude starts; FACTORY_RUNNER quiets plugin
    # SessionStart hooks; FACTORY_JOB tells the gate's Stop hook which job this is.
    env = {"CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1", "FACTORY_RUNNER": "1", "FACTORY_JOB": run["job_id"]}
    return argv, env


def result_object(stdout):
    text = stdout.strip()
    candidates = [text, *reversed(text.splitlines())]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            return data
    raise ValueError("no result object in claude's output")


def parse(stdout):
    data = result_object(stdout)
    by_model = {model: round(float(u.get("costUSD") or 0.0), 6)
                for model, u in (data.get("modelUsage") or {}).items()}
    cost = data.get("total_cost_usd")
    return {
        "session_id": data.get("session_id"),
        "model": max(by_model, key=by_model.get) if by_model else None,
        "usage": data.get("usage"),
        "cost_usd": round(float(cost), 6) if cost is not None else None,
        "cost_source": "cli" if cost is not None else None,
        "cost_by_model": by_model,
        "error": bool(data.get("is_error")),
    }
