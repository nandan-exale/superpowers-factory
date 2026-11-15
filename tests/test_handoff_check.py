import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import PLAN_PATH, SPEC_PATH, FactoryProject, git  # noqa: E402

CHECK = Path(__file__).resolve().parents[1] / "plugin" / "bin" / "factory-handoff-check"
REAL_GIT = shutil.which("git")
CHECKS = ("factory-installed", "gh-auth", "labels", "paths", "committed", "clean", "on-origin-base",
          "no-open-handoff")

# Answers by env var: FAKE_AUTH_EXIT, FAKE_LABELS (newline-separated), FAKE_ISSUES (JSON).
# Like the real `gh api`, it returns only the first page of 30 unless --paginate is given.
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_RECORD"], "a") as f:
    f.write(json.dumps(["gh", *args]) + "\n")
if args[:2] == ["auth", "status"]:
    sys.exit(int(os.environ.get("FAKE_AUTH_EXIT", "0")))
if args[0] == "api":
    names = os.environ.get("FAKE_LABELS", "factory\nfactory:planned").split("\n")
    print("\n".join(names if "--paginate" in args else names[:30]))
elif args[:2] == ["issue", "list"]:
    print(os.environ.get("FAKE_ISSUES", "[]"))
else:
    sys.exit("fake gh: unexpected " + " ".join(args))
'''

# Records git's argv, then runs the real git.
FAKE_GIT = f'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_RECORD"], "a") as f:
    f.write(json.dumps(["git", *sys.argv[1:]]) + "\\n")
os.execv({REAL_GIT!r}, ["git", *sys.argv[1:]])
'''


class HandoffCheckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.project = FactoryProject(self.tmp / "proj")
        self.repo = self.project.repo
        bindir = self.tmp / "fakebin"
        bindir.mkdir()
        for name, text in (("gh", FAKE_GH), ("git", FAKE_GIT)):
            (bindir / name).write_text(text)
            (bindir / name).chmod(0o755)
        self.record = self.tmp / "calls.jsonl"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "FAKE_"))}
        self.env.update(PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", FAKE_RECORD=str(self.record),
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

    def calls(self, tool=None):
        if not self.record.exists():
            return []
        calls = [json.loads(line) for line in self.record.read_text().splitlines()]
        return [c for c in calls if tool is None or c[0] == tool]

    def run_check(self, spec=SPEC_PATH, plan=PLAN_PATH, args=None, **env):
        argv = [spec, plan] if args is None else args
        res = subprocess.run([sys.executable, str(CHECK), *argv], cwd=self.repo, capture_output=True,
                             text=True, env={**self.env, **env})
        lines = res.stdout.splitlines()
        return res, lines, dict(line.split(": ", 1) for line in lines if re.match(r"[a-z_]+: ", line)
                                and not line.startswith(("PASS", "FAIL", "SKIP")))

    def commit_all(self, message="change"):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)
        git(self.repo, "push", "-q", "origin", "main")

    def assert_fails(self, res, lines, check, others_pass=False):
        self.assertEqual(res.returncode, 1, res.stdout)
        failed = [line for line in lines if line.startswith("FAIL")]
        self.assertTrue(any(line.startswith(f"FAIL {check}:") for line in failed), res.stdout)
        if others_pass:
            self.assertEqual(len(failed), 1, res.stdout)
            self.assertEqual(len([line for line in lines if line.startswith("PASS")]), len(CHECKS) - 1)

    def test_all_pass(self):
        res, lines, facts = self.run_check()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual([line for line in lines if line.startswith("PASS")], [f"PASS {c}" for c in CHECKS])
        self.assertEqual(facts, {"sha": self.project.sha, "base": "main", "branch": "main", "tasks": "1",
                                 "max_tasks_per_part": "8"})
        self.assertEqual(len(facts["sha"]), 40)
        self.assertFalse([line for line in lines if line.startswith("risky:")])

    def test_wrong_argument_count_is_a_usage_error(self):
        for args in ([], [SPEC_PATH], [SPEC_PATH, PLAN_PATH, "extra"]):
            res, lines, _ = self.run_check(args=args)
            self.assertEqual(res.returncode, 2)
            self.assertIn("Usage", res.stderr)
            self.assertEqual(lines, [])

    def test_factory_not_installed(self):
        (self.repo / "factory" / "bin" / "job").chmod(0o644)
        res, lines, _ = self.run_check()
        self.assert_fails(res, lines, "factory-installed")
        (self.repo / "factory" / "bin" / "job").unlink()
        res, lines, _ = self.run_check()
        self.assertIn("FAIL factory-installed:", res.stdout)

    def test_gh_not_logged_in(self):
        res, lines, _ = self.run_check(FAKE_AUTH_EXIT="1")
        self.assert_fails(res, lines, "gh-auth", others_pass=True)

    def test_missing_label_is_named(self):
        for present, missing in (("factory:planned", "factory"), ("factory", "factory:planned")):
            res, lines, _ = self.run_check(FAKE_LABELS=present)
            self.assert_fails(res, lines, "labels", others_pass=True)
            line = next(line for line in lines if line.startswith("FAIL labels:"))
            self.assertRegex(line, rf"missing labels {re.escape(missing)};")

    def test_labels_beyond_the_first_page_are_found(self):
        labels = [f"label-{i}" for i in range(150)] + ["factory", "factory:planned"]
        res, lines, _ = self.run_check(FAKE_LABELS="\n".join(labels))
        self.assertEqual(res.returncode, 0, res.stdout)
        api = self.calls("gh")
        api = [c for c in api if c[1] == "api"]
        self.assertEqual(len(api), 1)
        self.assertIn("--paginate", api[0])
        self.assertTrue(all("--limit" not in c for c in self.calls()))

    def test_bad_paths_fail_and_skip_the_rest(self):
        for bad in ("docs/superpowers/../secret.md", "README.md", "docs/superpowers/plans/plan.txt"):
            with self.subTest(bad=bad):
                res, lines, facts = self.run_check(plan=bad)
                self.assert_fails(res, lines, "paths")
                for check in ("committed", "clean", "on-origin-base", "no-open-handoff"):
                    self.assertIn(f"SKIP {check}: fix paths first", lines)
                self.assertEqual(facts, {})

    def test_spec_path_is_checked_too(self):
        res, lines, _ = self.run_check(spec="notes.md")
        self.assert_fails(res, lines, "paths")

    def test_shell_metacharacters_reach_nothing(self):
        bad = "docs/superpowers/plans/a;touch pwned.md"
        res, lines, _ = self.run_check(plan=bad)
        self.assert_fails(res, lines, "paths")
        self.assertFalse((self.repo / "pwned.md").exists())
        self.assertFalse(any("pwned" in arg or "touch" in arg for call in self.calls() for arg in call))

    def test_untracked_file_is_not_committed(self):
        (self.repo / "docs/superpowers/plans/new.md").write_text("# New\n")
        res, lines, _ = self.run_check(plan="docs/superpowers/plans/new.md")
        self.assert_fails(res, lines, "committed")

    def test_gitignored_file_is_not_committed(self):
        (self.repo / ".gitignore").write_text("docs/superpowers/plans/ignored.md\n")
        (self.repo / "docs/superpowers/plans/ignored.md").write_text("# Ignored\n")
        self.commit_all("ignore")
        res, lines, _ = self.run_check(plan="docs/superpowers/plans/ignored.md")
        self.assert_fails(res, lines, "committed")

    def test_edited_file_is_not_clean(self):
        (self.repo / PLAN_PATH).write_text("# Edited\n")
        res, lines, _ = self.run_check()
        self.assert_fails(res, lines, "clean", others_pass=True)

    def test_unpushed_commit_fails_only_on_origin_base(self):
        (self.repo / "local.txt").write_text("local\n")
        git(self.repo, "add", "local.txt")
        git(self.repo, "commit", "-q", "-m", "local only")
        res, lines, facts = self.run_check()
        self.assert_fails(res, lines, "on-origin-base", others_pass=True)
        self.assertEqual((facts["branch"], facts["base"]), ("main", "main"))

    def test_unpushed_commit_on_another_branch(self):
        self.project.unpushed_commit()
        git(self.repo, "checkout", "-q", "local-only")
        res, lines, facts = self.run_check()
        self.assert_fails(res, lines, "on-origin-base", others_pass=True)
        self.assertEqual((facts["branch"], facts["base"]), ("local-only", "main"))

    def test_failed_fetch_is_reported(self):
        git(self.repo, "remote", "set-url", "origin", str(self.tmp / "missing.git"))
        res, lines, _ = self.run_check()
        self.assert_fails(res, lines, "on-origin-base")
        self.assertIn("git fetch origin main failed", res.stdout)

    def test_missing_base_branch_config(self):
        config = json.loads((self.repo / "factory/config.json").read_text())
        del config["base_branch"]
        (self.repo / "factory/config.json").write_text(json.dumps(config))
        res, lines, facts = self.run_check()
        self.assert_fails(res, lines, "on-origin-base")
        self.assertIn("no usable base_branch", res.stdout)
        self.assertNotIn("base", facts)

    def test_unreadable_config_uses_default_labels(self):
        (self.repo / "factory/config.json").write_text("{not json")
        res, lines, facts = self.run_check()
        self.assert_fails(res, lines, "on-origin-base")
        self.assertIn("PASS labels", lines)
        self.assertEqual(facts["max_tasks_per_part"], "8")

    def test_labels_come_from_config(self):
        config = json.loads((self.repo / "factory/config.json").read_text())
        config["labels"]["planned"] = "planned-here"
        (self.repo / "factory/config.json").write_text(json.dumps(config))
        res, lines, _ = self.run_check()
        self.assertRegex(res.stdout, r"FAIL labels: missing labels planned-here;")
        searches = [c for c in self.calls("gh") if c[1:3] == ["issue", "list"]]
        self.assertEqual(searches[0][searches[0].index("--label") + 1], "planned-here")

    def test_open_handoff_issue_is_listed(self):
        issues = json.dumps([{"number": 5, "url": "https://github.com/o/r/issues/5"}])
        res, lines, _ = self.run_check(FAKE_ISSUES=issues)
        self.assert_fails(res, lines, "no-open-handoff", others_pass=True)
        self.assertIn("https://github.com/o/r/issues/5", res.stdout)
        search = next(c for c in self.calls("gh") if c[1:3] == ["issue", "list"])
        self.assertIn(f'"{PLAN_PATH}" in:body', search)
        self.assertEqual(search[search.index("--label") + 1], "factory:planned")

    def test_task_count_over_the_cap_is_information(self):
        (self.repo / PLAN_PATH).write_text("# Plan\n" + "".join(f"\n### Task {n}: step\n" for n in range(1, 10)))
        self.commit_all("nine tasks")
        res, lines, facts = self.run_check()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual((facts["tasks"], facts["max_tasks_per_part"]), ("9", "8"))

    def test_cap_comes_from_config(self):
        config_path = self.repo / "factory/config.json"
        config = json.loads(config_path.read_text())
        del config["handoff"]["max_tasks_per_part"]
        config_path.write_text(json.dumps(config))
        self.commit_all("no cap")
        self.assertEqual(self.run_check()[2]["max_tasks_per_part"], "8")
        config["handoff"]["max_tasks_per_part"] = 3
        config_path.write_text(json.dumps(config))
        self.commit_all("cap 3")
        self.assertEqual(self.run_check()[2]["max_tasks_per_part"], "3")

    def test_risky_lines_are_listed(self):
        plan = "# Plan\n\n### Task 1: Ship\n\ngit push origin main\nrun the tests\ngit checkout $BASE\n"
        (self.repo / PLAN_PATH).write_text(plan)
        self.commit_all("risky plan")
        res, lines, _ = self.run_check()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual([line for line in lines if line.startswith("risky:")],
                         ["risky: 5:git push origin main", "risky: 7:git checkout $BASE"])

    def test_risky_lines_use_the_base_branch_name(self):
        config_path = self.repo / "factory/config.json"
        config = json.loads(config_path.read_text())
        config["base_branch"] = "develop"
        config_path.write_text(json.dumps(config))
        (self.repo / PLAN_PATH).write_text('### Task 1: x\ngit checkout "$BASE"\ngit checkout develop\ngit checkout feature\n')
        git(self.repo, "checkout", "-q", "-b", "develop")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "develop")
        git(self.repo, "push", "-q", "-u", "origin", "develop")
        res, lines, _ = self.run_check()
        self.assertEqual([line for line in lines if line.startswith("risky:")],
                         ['risky: 2:git checkout "$BASE"', "risky: 3:git checkout develop"])

    def test_read_only(self):
        def snapshot():
            return (git(self.repo, "status", "--porcelain"), git(self.repo, "rev-parse", "HEAD"))

        before = snapshot()
        origin_before = git(self.tmp / "proj" / "origin.git", "rev-parse", "main")
        self.run_check()
        self.assertEqual(snapshot(), before)
        self.assertEqual(git(self.tmp / "proj" / "origin.git", "rev-parse", "main"), origin_before)
        self.assertEqual(git(self.repo, "rev-parse", "origin/main"), origin_before)
        for call in self.calls():
            self.assertNotIn(call[1:3], (["issue", "create"], ["issue", "edit"], ["label", "create"]))
            if call[0] == "git":
                self.assertNotIn(call[1], ("push", "commit", "add", "checkout", "tag", "merge", "reset"))

    def test_script_is_standalone_python(self):
        text = CHECK.read_text()
        self.assertTrue(text.startswith("#!/usr/bin/env python3\n"))
        self.assertTrue(os.access(CHECK, os.X_OK))
        self.assertNotIn("shell=True", text)
        self.assertNotIn("os.system", text)


if __name__ == "__main__":
    unittest.main()
