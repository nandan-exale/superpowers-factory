"""The factory's report and daily digest.

bin/job passes every helper it owns in as `env`, built on each call, so nothing is captured at import."""

import json
import re
from datetime import datetime, timedelta, timezone


def report_jobs(env):
    """(jobs, unreadable count), read without locks."""
    jobs, unreadable = [], 0
    for p in sorted(env.JOBS.iterdir()) if env.JOBS.exists() else []:
        if not (p / "job.json").exists():
            continue
        try:
            jobs.append(json.loads((p / "job.json").read_text()))
        except (OSError, ValueError):
            unreadable += 1
    return jobs, unreadable


def in_window(env, job, cutoff):
    ended = job.get("ended")
    return env.parse_time(job["started"]) >= cutoff or not ended or env.parse_time(ended) >= cutoff


def first_text_line(text):
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "-")


def median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def top(counts, n):
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def report_spend(env, window, days, cutoff, today):
    by_day = {(today - timedelta(days=k)).isoformat(): 0.0 for k in range(days - 1, -1, -1)}
    per_job = {}
    for j in window:
        for e in env.read_log(env.job_dir(j["id"]) / "log.jsonl"):
            t = env.parse_time(e["t"])
            if t >= cutoff:
                per_job[j["id"]] = per_job.get(j["id"], 0.0) + e["delta_usd"]
                day = t.date().isoformat()
                if day in by_day:
                    by_day[day] += e["delta_usd"]
    learner = sum(e["delta_usd"] for e in env.read_log(env.LEARNING / "log.jsonl") if env.parse_time(e["t"]) >= cutoff)
    return {"total": round(sum(per_job.values()), 2), "by_day": {d: round(u, 2) for d, u in by_day.items()},
            "top_jobs": [{"id": i, "usd": round(u, 2)} for i, u in top(per_job, 5)],
            "learner": round(learner, 2), "daily_cap": env.budgets()["daily_usd"], "today": round(env.daily_spend(), 2)}


def report_throughput(env, window):
    by_stage = {"merged": 0, "rejected": 0, "needs-human": 0, "needs-info": 0, "in progress": 0}
    for j in window:
        by_stage[j["stage"] if j["stage"] in by_stage else "in progress"] += 1
    merged = [j for j in window if j["stage"] == "merged" and j.get("ended")]
    rounds = [j["round"] for j in merged]
    hours = [(env.parse_time(j["ended"]) - env.parse_time(j["started"])).total_seconds() / 3600 for j in merged]
    return {"by_stage": by_stage, "rounds_median": median(rounds), "rounds_max": max(rounds) if rounds else None,
            "hours_to_merge_median": round(median(hours), 1) if hours else None}


def report_attention(env, jobs, now_dt):
    rows = []
    for j in jobs:
        if j["stage"] not in env.WAITING_REASON:
            continue
        name, heading = env.WAITING_REASON[j["stage"]]
        path = env.job_dir(j["id"]) / name
        reason = first_text_line(env.section(path, heading)) if path.exists() else "-"
        since = env.parse_time(j.get("ended") or j["started"])
        rows.append({"id": j["id"], "issue": j["issue"], "pr": j.get("pr"), "stage": j["stage"],
                     "waiting_hours": round((now_dt - since).total_seconds() / 3600, 1), "reason": reason})
    return sorted(rows, key=lambda r: -r["waiting_hours"])


def report_escalations(env, window):
    counts = {}
    for j in window:
        path = env.job_dir(j["id"]) / "decision.md"
        if env.first_line(path) != "ESCALATE":
            continue
        why = re.sub(r"\s+", " ", re.sub(r"\d+", "", first_text_line(env.section(path, "Why")).lower())).strip()
        counts[why] = counts.get(why, 0) + 1
    return [{"why": w, "count": c} for w, c in top(counts, 5)]


def report_findings(env, window):
    counts = {}
    for j in window:
        for path in sorted(env.round_dir(j).glob("review-*.md")) if j["round"] else []:
            for text in env.findings(path):
                tag = env.parse_finding(text)[0] or "untagged"
                counts[tag] = counts.get(tag, 0) + 1
    return [{"tag": t, "count": c} for t, c in top(counts, 10)]


def report_gate(env, window):
    firsts = [env.first_line(env.round_dir(j, 1) / "checks.md") for j in window
              if (env.round_dir(j, 1) / "checks.md").exists()]
    passed = sum(1 for line in firsts if line == "GATE: PASS")
    return {"first_try_pass": passed, "total": len(firsts),
            "rate": round(passed / len(firsts), 2) if firsts else None}


def report_data(env, days):
    now_dt = datetime.now(timezone.utc)
    cutoff = now_dt - timedelta(days=days)
    jobs, unreadable = report_jobs(env)
    window = [j for j in jobs if in_window(env, j, cutoff)]
    return {"days": days, "generated": env.now(), "unreadable": unreadable,
            "spend": report_spend(env, window, days, cutoff, now_dt.date()),
            "throughput": report_throughput(env, window), "attention": report_attention(env, jobs, now_dt),
            "escalations": report_escalations(env, window), "findings": report_findings(env, window),
            "gate": report_gate(env, window)}


def waited(hours):
    return f"{hours:.0f}h" if hours < 24 else f"{hours / 24:.0f}d"


def needs_you_line(data):
    items = [f"#{a['issue']} ({a['stage']}, {waited(a['waiting_hours'])})" for a in data["attention"]]
    return "Needs you: " + (", ".join(items) or "nothing")


def money(usd):
    return "-" if usd is None else f"${usd:.2f}"


def report_md(data):
    s, t, g = data["spend"], data["throughput"], data["gate"]
    lines = [needs_you_line(data), "", f"Factory report, last {data['days']} days ({data['generated']})", "",
             "## Spend", "",
             f"- Total {money(s['total'])}, learner {money(s['learner'])}; "
             f"last 24 h {money(s['today'])} of {money(s['daily_cap'])}",
             "- By day: " + ", ".join(f"{d[5:]} {money(u)}" for d, u in s["by_day"].items()),
             "- Top jobs: " + (", ".join(f"{j['id']} {money(j['usd'])}" for j in s["top_jobs"]) or "none"),
             "", "## Throughput", "",
             "- " + ", ".join(f"{k} {v}" for k, v in t["by_stage"].items()),
             f"- Rounds per merged job: median {t['rounds_median'] or '-'}, max {t['rounds_max'] or '-'}",
             f"- Hours from intake to merge (median): {t['hours_to_merge_median'] or '-'}",
             "", "## Needs you", ""]
    lines += [f"- #{a['issue']} ({a['stage']}, {waited(a['waiting_hours'])})"
              + (f" PR #{a['pr']}" if a["pr"] else "") + f": {a['reason']}" for a in data["attention"]] or ["- nothing"]
    lines += ["", "## Escalations", ""]
    lines += [f"- {e['count']} × {e['why']}" for e in data["escalations"]] or ["- none"]
    lines += ["", "## Findings", ""]
    lines += [f"- {f['tag']}: {f['count']}" for f in data["findings"]] or ["- none"]
    lines += ["", "## Gate", "",
              f"- First-try pass: {g['first_try_pass']} of {g['total']}"
              + (f" ({g['rate']:.0%})" if g["rate"] is not None else "")]
    if data["unreadable"]:
        lines += ["", f"{data['unreadable']} job folder(s) couldn't be read."]
    return "\n".join(lines) + "\n"


def write_report(env, data):
    env.JOBS.mkdir(parents=True, exist_ok=True)
    tmp = env.JOBS / "report.json.tmp"
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(env.JOBS / "report.json")


def cmd_report(env, args):
    days, as_json, write = 7, False, False
    rest = list(args)
    while rest:
        arg = rest.pop(0)
        if arg == "--days" and rest and rest[0].isdigit() and int(rest[0]) > 0:
            days = int(rest.pop(0))
        elif arg == "--json":
            as_json = True
        elif arg == "--write":
            write = True
        else:
            env.die(f"bad report arguments: {' '.join(args)} (use --days N with N ≥ 1, --json, --write)")
    data = report_data(env, days)
    if write:
        write_report(env, data)
    print(json.dumps(data, indent=2) if as_json else report_md(data), end="" if not as_json else "\n")


DIGEST_DEFAULTS = {"enabled": True, "hour": 9, "days": 1}
DIGEST_EVERY_HOURS = 20


def digest_config(env):
    return {**DIGEST_DEFAULTS, **(env.CONFIG.get("digest") or {})}


def digest_label(env):
    return env.LABELS.get("digest", "factory:digest")


def digest_issue(env):
    """The digest issue's number: an open one, else a reopened closed one, else a new pinned one."""
    label_name = digest_label(env)
    issues = sorted(env.gh_json("issue", "list", "--label", label_name, "--state", "all", "--limit", "20",
                            "--json", "number,state"), key=lambda i: i["number"])
    open_ones = [i for i in issues if i["state"] == "OPEN"]
    if open_ones:
        return open_ones[0]["number"]
    if issues:
        env.gh("issue", "reopen", str(issues[0]["number"]))
        return issues[0]["number"]
    env.gh("label", "create", label_name, "--color", "0E8A16", "--description", "Daily factory digest", "--force")
    url = env.gh("issue", "create", "--title", "Factory digest", "--label", label_name,
             "--body", "The factory posts a daily summary here.").strip()
    m = re.search(r"/issues/(\d+)$", url)
    if not m:
        raise env.Refused(f"gh issue create printed {url!r}, not an issue URL")
    number = int(m.group(1))
    try:
        env.gh("issue", "pin", str(number))
    except env.Refused:
        pass  # pinning is a convenience; the label finds the issue
    return number


def cmd_digest(env):
    cfg = digest_config(env)
    if not cfg["enabled"]:
        print("DIGEST: off")
        return
    if datetime.now().hour < cfg["hour"]:
        print(f"DIGEST: not yet (after {cfg['hour']}:00)")
        return
    path = env.JOBS / "digest.json"
    last = json.loads(path.read_text()) if path.exists() else {}
    if last.get("posted") and datetime.now(timezone.utc) - env.parse_time(last["posted"]) < timedelta(hours=DIGEST_EVERY_HOURS):
        print(f"DIGEST: already posted at {last['posted']}")
        return
    try:
        number = digest_issue(env)
        env.gh("issue", "comment", str(number), "--body", f"{env.MARKER}\n{report_md(report_data(env, cfg['days']))}")
    except env.Refused as e:
        print(f"NOTE: digest not posted: {str(e).splitlines()[0]}")
        return
    env.JOBS.mkdir(parents=True, exist_ok=True)
    tmp = env.JOBS / "digest.json.tmp"
    tmp.write_text(json.dumps({"posted": env.now(), "issue": number}) + "\n")
    tmp.replace(path)
    print(f"DIGEST: posted on #{number}")
