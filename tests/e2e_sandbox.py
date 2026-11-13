"""A throwaway e2e sandbox: a clone whose origin URL is on github.com but whose pushes go to a
local bare repo, plus fake gh, claude and security commands that record their calls."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
VENDOR_CONFIG = PLUGIN / "vendor" / "factory" / "factory" / "config.json"
URL = "https://github.com/tester/factory-e2e.git"

FAKE_GH = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_RECORD"], "a") as f:
    f.write(json.dumps(["gh", *args]) + "\n")
if args[:2] == ["auth", "status"]:
    sys.exit(int(os.environ.get("FAKE_GH_AUTH_EXIT", "0")))
if args[:2] == ["issue", "create"]:
    print("https://github.com/tester/factory-e2e/issues/7")
elif args[:2] == ["issue", "view"]:
    names = [n for n in os.environ.get("FAKE_LABELS", "").split(",") if n]
    print(json.dumps({"labels": [{"name": n} for n in names]}))
elif args[:2] == ["issue", "list"]:
    print(os.environ.get("FAKE_LEARNING_ISSUES", "[]"))
elif args[:2] == ["pr", "view"]:
    print(json.dumps({"state": os.environ.get("FAKE_PR_STATE", "MERGED")}))
'''

# Each run writes job 001-e2e for issue 7 at $FAKE_STAGE and logs $FAKE_DELTA of spend.
FAKE_CLAUDE = r'''
import datetime, json, os, sys
with open(os.environ["FAKE_RECORD"], "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "runner": os.environ.get("FACTORY_RUNNER"),
                        "scrub": os.environ.get("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB")}) + "\n")
job = os.path.join("factory", "jobs", "001-e2e")
os.makedirs(job, exist_ok=True)
with open(os.path.join(job, "job.json"), "w") as f:
    json.dump({"id": "001-e2e", "issue": 7, "stage": os.environ.get("FAKE_STAGE", "merged"),
               "round": 1, "pr": 3, "branch": "factory/001-e2e"}, f)
t = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
with open(os.path.join(job, "log.jsonl"), "a") as f:
    f.write(json.dumps({"t": t, "delta_usd": float(os.environ.get("FAKE_DELTA", "0.10"))}) + "\n")
print(json.dumps({"total_cost_usd": float(os.environ.get("FAKE_SESSION_COST", "0.05")),
                  "result": os.environ.get("FAKE_RESULT", "done")}))
'''

FAKE_SECURITY = r'''
import os, sys
sys.exit(int(os.environ.get("FAKE_SECURITY_EXIT", "1")))
'''


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def write_exe(path, text):
    path.write_text(text)
    path.chmod(0o755)


class E2ESandbox:
    def __init__(self, root):
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.bare = root / "origin.git"
        self.repo = root / "factory-e2e"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.bare))
        git(root, "clone", "-q", str(self.bare), str(self.repo))
        for key, value in (("user.email", "t@example.com"), ("user.name", "T"),
                           ("commit.gpgsign", "false"), (f"url.{self.bare}.pushInsteadOf", URL)):
            git(self.repo, "config", key, value)
        git(self.repo, "remote", "set-url", "origin", URL)
        factory = self.repo / "factory"
        (factory / "bin").mkdir(parents=True)
        write_exe(factory / "bin" / "job", "#!/bin/sh\nexit 0\n")
        write_exe(factory / "bin" / "doctor", '#!/bin/sh\nexit "${FAKE_DOCTOR_EXIT:-0}"\n')
        shutil.copy(VENDOR_CONFIG, factory / "config.json")
        (factory / "runner-settings.json").write_text("{}\n")
        (self.repo / ".gitignore").write_text("/factory/jobs/\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")
        git(self.repo, "push", "-q", "-u", "origin", "main")
        self.fakebin = root / "bin"
        self.fakebin.mkdir()
        for name, body in (("gh", FAKE_GH), ("claude", FAKE_CLAUDE), ("security", FAKE_SECURITY)):
            write_exe(self.fakebin / name, f"#!{sys.executable}\n{body}")
        self.record = root / "record.jsonl"
        self.record.touch()

    def env(self, **extra):
        return {"PATH": f"{self.fakebin}{os.pathsep}{os.environ['PATH']}", "FAKE_RECORD": str(self.record),
                **{k: str(v) for k, v in extra.items()}}

    def calls(self):
        return [json.loads(line) for line in self.record.read_text().splitlines() if line]

    def claude_calls(self):
        return [c for c in self.calls() if isinstance(c, dict)]

    def gh_calls(self):
        return [c[1:] for c in self.calls() if isinstance(c, list)]

    def origin_config(self):
        return json.loads(git(self.root, "--git-dir", str(self.bare), "show", "main:factory/config.json"))
