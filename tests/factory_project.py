"""A throwaway project with a bare origin and the vendored factory scripts."""

import contextlib
import importlib.machinery
import importlib.util
import io
import shutil
import subprocess
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
VENDOR = PLUGIN / "vendor" / "factory"
SPEC_PATH = "docs/superpowers/specs/2026-11-12-widget-design.md"
PLAN_PATH = "docs/superpowers/plans/2026-11-12-widget.md"
SPEC_TEXT = "# Widget design\n\nThe widget spins.\n"
PLAN_TEXT = "# Widget plan\n\n### Task 1: Spin\n"


def git(cwd, *args):
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def plan_body(commit, spec=SPEC_PATH, plan=PLAN_PATH, risk="medium", surfaces="[ui]"):
    return (
        "Build the widget.\n\n"
        "```factory-plan\n"
        f"spec: {spec}\nplan: {plan}\ncommit: {commit}\nrisk: {risk}\nsurfaces: {surfaces}\n"
        "```\n"
    )


class FactoryProject:
    def __init__(self, root):
        root = Path(root).resolve()
        self.origin = root / "origin.git"
        self.repo = root / "project"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.origin, "config", "receive.autogc", "false")
        git(root, "clone", "-q", str(self.origin), str(self.repo))
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / "factory" / "bin").mkdir(parents=True)
        for script in ("job", "route"):
            shutil.copy(VENDOR / "factory" / "bin" / script, self.repo / "factory" / "bin" / script)
        shutil.copy(VENDOR / "factory" / "config.json", self.repo / "factory" / "config.json")
        for path, text in ((SPEC_PATH, SPEC_TEXT), (PLAN_PATH, PLAN_TEXT)):
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "init")
        git(self.repo, "push", "-q", "-u", "origin", "main")
        self.sha = git(self.repo, "rev-parse", "HEAD")
        self.gh_calls = []
        self.issue = None

    def unpushed_commit(self):
        """A commit that exists locally but not on origin/main."""
        git(self.repo, "checkout", "-q", "-b", "local-only")
        (self.repo / "local.txt").write_text("local\n")
        git(self.repo, "add", "local.txt")
        git(self.repo, "commit", "-q", "-m", "local only")
        sha = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")
        return sha

    def set_issue(self, body, labels=("factory", "factory:planned"), number=7):
        self.issue = {
            "number": number, "title": "Build the widget", "body": body,
            "author": {"login": "operator"}, "labels": [{"name": n} for n in labels],
            "state": "OPEN", "url": f"https://github.com/o/r/issues/{number}", "comments": [],
        }

    def load_job(self):
        """Import this project's bin/job as a module with gh faked out."""
        path = self.repo / "factory" / "bin" / "job"
        loader = importlib.machinery.SourceFileLoader(f"factory_job_{id(self)}", str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)

        def fake_gh(*args):
            self.gh_calls.append(args)
            return ""

        mod.gh = fake_gh
        mod.fetch_issue = lambda number: self.issue
        mod.operator = lambda: "operator"
        return mod

    def create_job(self, mod):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mod.cmd_create(str(self.issue["number"]))
        return out.getvalue().strip()
