"""The scripts the orchestrator changes state through (job, gate, route), plus gh and job.json reads."""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Out:
    code: int
    out: str
    err: str

    @property
    def ok(self):
        return self.code == 0

    @property
    def text(self):
        return "\n".join(t for t in (self.out.strip(), self.err.strip()) if t)


class JobCli:
    def __init__(self, repo):
        self.repo = Path(repo)
        self.bin = self.repo / "factory" / "bin"

    def _run(self, argv, stdin=None):
        res = subprocess.run(argv, cwd=self.repo, input=stdin, capture_output=True, text=True)
        return Out(res.returncode, res.stdout, res.stderr)

    def job(self, *args, stdin=None):
        return self._run([sys.executable, str(self.bin / "job"), *map(str, args)], stdin)

    def gate(self, job_id):
        return self._run([sys.executable, str(self.bin / "gate"), job_id])

    def route(self, job_id):
        return self._run([sys.executable, str(self.bin / "route"), job_id])

    def gh(self, *args):
        return self._run(["gh", *map(str, args)])

    def state(self, job_id):
        return json.loads((self.repo / "factory" / "jobs" / job_id / "job.json").read_text())

    def config(self):
        return json.loads((self.repo / "factory" / "config.json").read_text())
