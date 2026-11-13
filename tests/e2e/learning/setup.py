#!/usr/bin/env python3
"""Seed three finished jobs whose code reviews share a [convention] finding, so `job learn` fires.

Usage: setup.py <sandbox>. Clears factory/jobs/learning/ first: its state.json would otherwise
hold back a tag filed in an earlier run.
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REVIEW = """VERDICT: CHANGES

## Summary
- Seeded by the e2e learning scenario.

## Findings
1. [convention] app.py:{line} use the module's `log()` helper instead of print()
"""


def main(sandbox):
    jobs = Path(sandbox) / "factory" / "jobs"
    shutil.rmtree(jobs / "learning", ignore_errors=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for n in (1, 2, 3):
        job_id = f"e2e-learn-{n}"
        d = jobs / job_id
        (d / "round-1").mkdir(parents=True, exist_ok=True)
        job = {"id": job_id, "issue": 900000 + n, "title": f"Seeded job {n}", "issue_url": "", "pr": None,
               "pr_url": "", "branch": f"factory/{job_id}", "worktree": "", "stage": "merged", "round": 1,
               "round_limit": 3, "intake": {}, "agents": {}, "gate": "PASS", "reviews": {"code": "CHANGES"},
               "cost_usd": 0.0, "started": now, "ended": now, "job_usd": 25}
        (d / "job.json").write_text(json.dumps(job, indent=2) + "\n")
        (d / "round-1" / "review-code.md").write_text(REVIEW.format(line=10 * n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
