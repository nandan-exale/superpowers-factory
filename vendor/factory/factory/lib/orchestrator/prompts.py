"""Every prompt the orchestrator sends, worded as the factory skill worded it for the agents."""

PORT_OFFSET = {"builder": 0, "reviewer-ux": 1, "reviewer-ui": 2}
RESUMING = ("You are resuming a build another builder started: read build.md and `git log` to see how "
            "far it got (and, when plan.md exists, which plan tasks are ticked off), then carry on.")


def header(repo, job, base, worktree=True):
    where = (f"Worktree: {job['worktree']}." if worktree
             else "Worktree: none, it doesn't exist yet. Work in the main checkout.")
    line = (f"Job: {job['id']}. Job folder: {repo}/factory/jobs/{job['id']}/. Main checkout: {repo}. "
            f"{where} Branch: {job['branch']}. Base: origin/{base}. Issue: #{job['issue']}.")
    if job.get("tasks"):
        line += f" Tasks: {job['tasks']} of {job['plan_tasks']}."
    return line


def port(config, job_id, role):
    """The port an agent may serve pages on, or None for roles that open no pages."""
    if role not in PORT_OFFSET:
        return None
    ports = config.get("ports") or {"base": 5100, "step": 10}
    return ports["base"] + ports["step"] * int(job_id.split("-", 1)[0]) + PORT_OFFSET[role]


def build(head, n, port_, why=""):
    return f"{head} Build round {n}. Port: {port_}." + (f" {why}" if why else "")


def review(head, n, port_):
    return f"{head} Review round {n}." + (f" Port: {port_}." if port_ is not None else "")


def approve(head, pr, n):
    return f"{head} PR: #{pr}. Final round: {n}."


def learner(repo, tag_dir, tag):
    return f"Job folder: {repo}/factory/jobs/learning/{tag_dir}/. {tag}"


def gate_failed(prev):
    return f"The gate failed: read round-{prev}/checks.md and checks.log, fix it, push, and update build.md."


def changes(prev, n):
    return (f"Round {prev} reviews are in round-{prev}/. Address every VERDICT: CHANGES, push, "
            f"and update build.md for round {n}.")


def pr_comments(files):
    return f"Also address PR comments in {' '.join(files)}."


def pr_arrived(files, n):
    return f"PR comments arrived: read {' '.join(files)} and address them, push, and update build.md for round {n}."


def refused(text):
    return f"The factory refused your result:\n\n{text}\n\nFix that, then reply again."
