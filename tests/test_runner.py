import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from installed_project import VENDOR, InstalledProject, git, load_script

FAKE_CLAUDE = """#!{python}
import json, os, sys, time
with open(os.environ["FAKE_RECORD"], "a") as f:
    f.write(json.dumps({{"tool": "claude", "argv": sys.argv[1:],
        "has_token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == "tok-123",
        "has_api_key": "ANTHROPIC_API_KEY" in os.environ,
        "has_base_url": "ANTHROPIC_BASE_URL" in os.environ,
        "scrub": os.environ.get("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB")}}) + "\\n")
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


class TickTest(RunnerCase):
    WORK = [{"number": 7, "title": "Build the widget"}]

    def test_idle_queue_does_not_call_claude(self):
        res = self.runner("tick")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.calls("claude"), [])
        self.assertTrue(self.log_lines()[-1].endswith(" idle"))

    def test_work_runs_claude_headless_with_token_and_no_api_vars(self):
        self.set_issues(self.WORK)
        res = self.runner("tick")
        self.assertEqual(res.returncode, 0, res.stderr)
        [call] = self.calls("claude")
        self.assertEqual(call["argv"][:4], ["-p", "/factory run", "--output-format", "json"])
        self.assertIn("--permission-mode", call["argv"])
        self.assertEqual(call["argv"][call["argv"].index("--permission-mode") + 1], "dontAsk")
        settings = call["argv"][call["argv"].index("--settings") + 1]
        self.assertTrue(settings.endswith("factory/runner-settings.json"))
        self.assertTrue(call["has_token"])
        self.assertFalse(call["has_api_key"])
        self.assertFalse(call["has_base_url"])
        line = self.log_lines()[-1]
        self.assertRegex(line, r" ran exit=0 \d+s cost=\$1\.25$")
        self.assertNotIn("tok-123", line + json.dumps(call["argv"]))
        runs = list((self.p.root / "factory/jobs/runs").glob("*.json"))
        self.assertEqual(len(runs), 1)
        self.assertEqual(json.loads(runs[0].read_text())["result"], "done")

    def test_token_is_read_from_the_configured_keychain_item(self):
        self.set_issues(self.WORK)
        self.runner("tick")
        [call] = self.calls("security")
        self.assertEqual(call["argv"], ["find-generic-password", "-s", "factory-claude-token", "-w"])

    def test_missing_token_is_an_error(self):
        self.set_issues(self.WORK)
        res = self.runner("tick", FAKE_SECURITY_EXIT="44", FAKE_SECURITY_OUT="")
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.calls("claude"), [])
        self.assertIn("error: no token in Keychain item factory-claude-token", self.log_lines()[-1])

    def test_dirty_tree_is_skipped_and_untouched(self):
        self.set_issues(self.WORK)
        self.p.write("AGENTS.md", "# Agents\nmine\n")
        res = self.runner("tick")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(self.calls("claude"), [])
        self.assertIn("skipped: uncommitted changes", self.log_lines()[-1])
        self.assertEqual((self.p.root / "AGENTS.md").read_text(), "# Agents\nmine\n")

    def test_other_branch_is_skipped(self):
        git(self.p.root, "checkout", "-q", "-b", "feature")
        res = self.runner("tick")
        self.assertEqual(res.returncode, 0)
        self.assertIn("skipped: on feature, not main", self.log_lines()[-1])

    def test_pull_brings_in_new_commits(self):
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", str(self.tmp / "origin.git"), str(other))
        (other / "NEW.md").write_text("new\n")
        git(other, "add", "NEW.md")
        git(other, "-c", "user.email=t@e.com", "-c", "user.name=t", "-c", "commit.gpgsign=false",
            "commit", "-q", "-m", "new")
        git(other, "push", "-q", "origin", "main")
        self.runner("tick")
        self.assertTrue((self.p.root / "NEW.md").exists())

    def test_busy_when_locked(self):
        import fcntl
        lock_path = self.p.git_dir / "factory-runner.lock"
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            res = self.runner("tick")
        self.assertEqual(res.returncode, 0)
        self.assertTrue(self.log_lines()[-1].endswith(" busy"))

    def test_timeout_kills_claude(self):
        self.set_issues(self.WORK)
        res = self.runner("tick", FACTORY_RUNNER_MAX_SECONDS="1", FAKE_CLAUDE_SLEEP="10")
        self.assertEqual(res.returncode, 1)
        self.assertRegex(self.log_lines()[-1], r" timeout after \d+s$")

    def test_claude_failure_is_logged_with_exit_code(self):
        self.set_issues(self.WORK)
        res = self.runner("tick", FAKE_CLAUDE_EXIT="3")
        self.assertEqual(res.returncode, 1)
        self.assertIn(" ran exit=3 ", self.log_lines()[-1])

    def test_every_tick_logs_exactly_one_line(self):
        self.runner("tick")
        self.runner("tick")
        self.assertEqual(len(self.log_lines()), 2)


class LaunchAgentTest(RunnerCase):
    def plist(self):
        res = self.runner("install", "--dry-run")
        self.assertEqual(res.returncode, 0, res.stderr)
        return plistlib.loads(res.stdout.encode())

    def test_dry_run_plist(self):
        p = self.plist()
        self.assertTrue(p["Label"].startswith("com.superpowers-factory."))
        self.assertRegex(p["Label"], r"^[a-z0-9.-]+$")
        self.assertEqual(p["ProgramArguments"][1:], [str(self.p.root / "factory/bin/runner"), "tick"])
        self.assertEqual(p["StartInterval"], 15 * 60)
        self.assertTrue(p["RunAtLoad"])
        self.assertEqual(p["WorkingDirectory"], str(self.p.root))
        self.assertEqual(p["StandardOutPath"], str(self.p.root / "factory/jobs/runner.launchd.log"))
        self.assertIn(str(self.p.fakebin), p["EnvironmentVariables"]["PATH"])

    def test_dry_run_changes_nothing(self):
        self.runner("install", "--dry-run")
        self.assertFalse((self.home / "Library").exists())
        self.assertEqual(self.calls("launchctl"), [])

    @unittest.skipUnless(sys.platform == "darwin", "launchd only")
    def test_install_writes_plist_and_bootstraps(self):
        res = self.runner("install")
        self.assertEqual(res.returncode, 0, res.stderr)
        plists = list((self.home / "Library/LaunchAgents").glob("com.superpowers-factory.*.plist"))
        self.assertEqual(len(plists), 1)
        argvs = [c["argv"] for c in self.calls("launchctl")]
        self.assertEqual(argvs[0][0], "bootout")
        self.assertEqual(argvs[-1], ["bootstrap", f"gui/{os.getuid()}", str(plists[0])])

    @unittest.skipUnless(sys.platform == "darwin", "launchd only")
    def test_uninstall_removes_plist(self):
        self.runner("install")
        res = self.runner("uninstall")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(list((self.home / "Library/LaunchAgents").glob("*.plist")), [])

    @unittest.skipUnless(sys.platform == "darwin", "launchd only")
    def test_status_shows_state_and_log_tail(self):
        self.runner("tick")
        res = self.runner("status", FAKE_LAUNCHCTL_EXIT="113")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("not loaded", res.stdout)
        self.assertIn(" idle", res.stdout)

    @unittest.skipIf(sys.platform == "darwin", "non-macOS behavior")
    def test_install_outside_macos_refuses(self):
        res = self.runner("install")
        self.assertEqual(res.returncode, 1)
        self.assertIn("launchd only", res.stderr)


class SecurityTest(RunnerCase):
    WORK = [{"number": 7, "title": "Build the widget"}]
    HOOKS_ERROR = "error: git hooks or fsmonitor configured in this clone; remove them"

    def settings(self):
        return json.loads((VENDOR / "factory/runner-settings.json").read_text())

    def test_settings_deny_edits_to_git_and_the_runner_s_own_files(self):
        deny = self.settings()["permissions"]["deny"]
        for tool in ("Edit", "Write"):
            for path in ("./.git/**", "./factory/bin/**", "./factory/runner-settings.json",
                         "./factory/config.json", "./factory/checks.sh", "./.claude/**",
                         "~/.ssh/**", "~/.claude/**", "~/Library/LaunchAgents/**"):
                self.assertIn(f"{tool}({path})", deny)

    def test_settings_deny_destructive_git_and_gh(self):
        deny = self.settings()["permissions"]["deny"]
        for rule in ("Bash(git push * --force*)", "Bash(git push * -f*)", "Bash(git push *+*)",
                     "Bash(git push --force-with-lease*)", "Bash(gh repo delete*)",
                     "Bash(gh repo edit*)", "Bash(gh api -X DELETE*)", "Bash(gh api --method DELETE*)"):
            self.assertIn(rule, deny)

    def test_settings_allow_local_binding(self):
        self.assertIs(self.settings()["sandbox"]["network"]["allowLocalBinding"], True)

    def test_git_helper_disables_hooks_fsmonitor_and_prompts(self):
        module = load_script("runner_under_test", self.p.root / "factory/bin/runner")
        with mock.patch.object(module.subprocess, "run") as run:
            module.git("status")
        args, kwargs = run.call_args
        self.assertEqual(args[0][:5], ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"])
        self.assertEqual(args[0][5:], ["status"])
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertIn("BatchMode=yes", kwargs["env"]["GIT_SSH_COMMAND"])

    def assertRefusesHooks(self):
        self.set_issues(self.WORK)
        res = self.runner("tick")
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.calls("claude"), [])
        self.assertEqual(self.log_lines()[-1].split(" ", 1)[1], self.HOOKS_ERROR)

    def test_executable_hook_is_refused(self):
        hook = self.p.git_dir / "hooks" / "post-merge"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        self.assertRefusesHooks()

    def test_sample_hooks_are_fine(self):
        sample = self.p.git_dir / "hooks" / "pre-commit.sample"
        sample.parent.mkdir(exist_ok=True)
        sample.write_text("#!/bin/sh\nexit 0\n")
        sample.chmod(0o755)
        res = self.runner("tick")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(self.log_lines()[-1].endswith(" idle"))

    def test_hooks_path_in_local_config_is_refused(self):
        git(self.p.root, "config", "--local", "core.hooksPath", ".githooks")
        self.assertRefusesHooks()

    def test_fsmonitor_in_local_config_is_refused(self):
        git(self.p.root, "config", "--local", "core.fsmonitor", "true")
        self.assertRefusesHooks()

    def test_claude_child_scrubs_the_token_from_its_subprocesses(self):
        self.set_issues(self.WORK)
        self.runner("tick")
        [call] = self.calls("claude")
        self.assertEqual(call["scrub"], "1")


if __name__ == "__main__":
    unittest.main()
