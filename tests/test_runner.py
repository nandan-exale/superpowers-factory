import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from installed_project import InstalledProject, git

FAKE_CLAUDE = """#!{python}
import json, os, sys, time
with open(os.environ["FAKE_RECORD"], "a") as f:
    f.write(json.dumps({{"tool": "claude", "argv": sys.argv[1:],
        "has_token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == "tok-123",
        "has_api_key": "ANTHROPIC_API_KEY" in os.environ,
        "has_base_url": "ANTHROPIC_BASE_URL" in os.environ}}) + "\\n")
time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "0")))
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False,
                  "total_cost_usd": 1.25, "result": "done"}}))
sys.exit(int(os.environ.get("FAKE_CLAUDE_EXIT", "0")))
"""

# Answers `gh issue list` from $FAKE_ISSUES (JSON list) and everything else with [].
FAKE_GH_QUEUE = """#!{python}
import os, sys
if sys.argv[1:3] == ["issue", "list"]:
    sys.stdout.write(open(os.environ["FAKE_ISSUES"]).read())
else:
    sys.stdout.write("[]")
"""


class RunnerCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.p = InstalledProject(self.tmp)
        self.record = self.tmp / "record.jsonl"
        self.issues = self.tmp / "issues.json"
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.set_issues([])
        for name, text in (("claude", FAKE_CLAUDE), ("gh", FAKE_GH_QUEUE)):
            path = self.p.fakebin / name
            path.write_text(text.format(python=sys.executable))
            path.chmod(0o755)
        self.add_origin()

    def add_origin(self):
        origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.p.root, "branch", "-M", "main")
        git(self.p.root, "remote", "add", "origin", str(origin))
        git(self.p.root, "push", "-q", "-u", "origin", "main")

    def set_issues(self, issues):
        self.issues.write_text(json.dumps(issues))

    def runner(self, *args, **env):
        full = self.p.env()
        full.update({"FAKE_RECORD": str(self.record), "FAKE_ISSUES": str(self.issues),
                     "HOME": str(self.home), "FAKE_SECURITY_OUT": "tok-123\n",
                     "ANTHROPIC_API_KEY": "must-be-removed", "ANTHROPIC_BASE_URL": "http://x"})
        full.update(env)
        return subprocess.run([sys.executable, str(self.p.root / "factory/bin/runner"), *args],
                              capture_output=True, text=True, cwd=self.p.root, env=full)

    def calls(self, tool):
        if not self.record.exists():
            return []
        return [c for c in map(json.loads, self.record.read_text().splitlines()) if c["tool"] == tool]

    def log_lines(self):
        path = self.p.root / "factory/jobs/runner.log"
        return path.read_text().splitlines() if path.exists() else []

    def edit_config(self, change):
        path = self.p.root / "factory/config.json"
        cfg = json.loads(path.read_text())
        change(cfg)
        path.write_text(json.dumps(cfg))
        self.p.commit_all("config")
        git(self.p.root, "push", "-q", "origin", "main")


class ConfigTest(RunnerCase):
    def test_bad_interval_exits_naming_the_key(self):
        self.edit_config(lambda c: c["runner"].update(interval_minutes=0))
        res = self.runner("tick")
        self.assertEqual(res.returncode, 1)
        self.assertIn("runner.interval_minutes", res.stderr)

    def test_missing_runner_config_exits(self):
        self.edit_config(lambda c: c.pop("runner"))
        res = self.runner("tick")
        self.assertEqual(res.returncode, 1)
        self.assertIn("no runner object", res.stderr)

    def test_bad_arguments_print_usage(self):
        res = self.runner("frobnicate")
        self.assertEqual(res.returncode, 1)
        self.assertIn("Usage:", res.stderr)


if __name__ == "__main__":
    unittest.main()
