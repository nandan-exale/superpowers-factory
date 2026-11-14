"""The rule for read-only agents: the checkout stays as it was, and only the role's own files in the job
folder change. Checked by comparing snapshots taken before and after the agents run."""

import subprocess

BOOKKEEPING = {"job.json", "job.tmp", "log.jsonl", ".lock", "evidence.md"}


def folder_files(folder):
    files = {}
    for path in folder.rglob("*"):
        rel = path.relative_to(folder).as_posix()
        if path.is_file() and rel.split("/", 1)[0] != "runs" and rel not in BOOKKEEPING:
            st = path.stat()
            files[rel] = (st.st_mtime_ns, st.st_size)
    return files


def git_out(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout


def snapshot(folder, checkout, compare_head):
    """compare_head is False for the main checkout, which other jobs' merges may fast-forward."""
    return {
        "files": folder_files(folder),
        "head": git_out(checkout, "rev-parse", "HEAD").strip() if compare_head else None,
        "status": git_out(checkout, "status", "--porcelain", "--untracked-files=all"),
    }


def violations(before, after, own):
    problems = []
    if before["head"] != after["head"] or before["status"] != after["status"]:
        was, now = set(before["status"].splitlines()), set(after["status"].splitlines())
        changed = sorted((was ^ now)) or ["HEAD moved"]
        problems.append("changed the checkout: " + ", ".join(line.strip() for line in changed))
    keys = set(before["files"]) | set(after["files"])
    changed = sorted(k for k in keys if before["files"].get(k) != after["files"].get(k))
    stray = [k for k in changed if k not in own]
    if stray:
        problems.append("wrote files it doesn't own: " + ", ".join(stray))
    return problems


def quarantine(folder, own):
    """Move a rejected run's own files to runs/, so the next step doesn't read them as valid."""
    (folder / "runs").mkdir(exist_ok=True)
    for rel in sorted(own):
        path = folder / rel
        if path.exists():
            path.rename(folder / "runs" / (rel.replace("/", "--") + ".rejected"))
