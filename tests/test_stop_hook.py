import json
import tempfile
import time
import unittest

from installed_project import CHECKS_SH, InstalledProject

STAMP = "factory-stop-hook.pass"
FAILED = "factory-stop-hook.failed"


class StopHookTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p = InstalledProject(tmp.name)

    def hook(self, payload=None, stdin=None, **env):
        stdin = stdin if stdin is not None else json.dumps(payload or {})
        return self.p.run("stop-hook", stdin=stdin, env=env)

    def edit(self, text="edit"):
        self.p.write("AGENTS.md", f"# Agents\n{text}\n")

    def test_clean_tree_skips_checks(self):
        res = self.hook()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.p.checks_runs(), 0)

    def test_passing_checks_allow_stop_and_write_stamp(self):
        self.edit()
        res = self.hook()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.p.checks_runs(), 1)
        self.assertTrue((self.p.git_dir / STAMP).is_file())

    def test_unchanged_state_uses_cache(self):
        self.edit()
        self.hook()
        res = self.hook()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.p.checks_runs(), 1)

    def test_new_edit_after_pass_reruns(self):
        self.edit("a")
        self.hook()
        self.edit("b")
        self.hook()
        self.assertEqual(self.p.checks_runs(), 2)

    def test_untracked_file_changes_key(self):
        self.edit()
        self.hook()
        self.p.write("notes.txt", "new\n")
        self.hook()
        self.assertEqual(self.p.checks_runs(), 2)

    def test_ignored_job_state_does_not_count(self):
        self.p.write("factory/jobs/001-x/job.json", "{}\n")
        self.p.write(".worktrees/001-x/file.txt", "x\n")
        res = self.hook()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.p.checks_runs(), 0)

    def test_failing_checks_block_with_output_tail(self):
        self.p.set_checks_result(1)
        self.edit()
        res = self.hook()
        self.assertEqual(res.returncode, 2)
        self.assertIn("factory/checks.sh failed (exit 1)", res.stderr)
        self.assertIn("checks output line", res.stderr)
        self.assertFalse((self.p.git_dir / STAMP).exists())

    def test_failure_is_not_cached(self):
        self.p.set_checks_result(1)
        self.edit()
        self.hook()
        self.hook()
        self.assertEqual(self.p.checks_runs(), 2)

    def test_second_stop_does_not_block_again(self):
        self.p.set_checks_result(1)
        self.edit()
        res = self.hook({"stop_hook_active": True})
        self.assertEqual(res.returncode, 0)
        self.assertIn("factory/checks.sh failed", res.stderr)

    def test_checks_run_without_claude_credentials(self):
        self.p.set_checks_script(
            "#!/usr/bin/env bash\nenv > \"$(git rev-parse --git-dir)/checks-env\"\n")
        self.edit()
        secrets = {"CLAUDE_CODE_OAUTH_TOKEN": "tok", "ANTHROPIC_API_KEY": "key",
                   "ANTHROPIC_AUTH_TOKEN": "auth", "ANTHROPIC_BASE_URL": "http://x"}
        self.assertEqual(self.hook(**secrets).returncode, 0)
        seen = (self.p.git_dir / "checks-env").read_text()
        self.assertIn("PATH=", seen)
        for name in secrets:
            self.assertNotIn(name, seen)

    def test_missing_checks_does_not_block(self):
        (self.p.root / "factory" / "checks.sh").unlink()
        res = self.hook()
        self.assertEqual(res.returncode, 0)
        self.assertIn("factory/checks.sh not found", res.stderr)

    def test_non_object_payload_is_ignored(self):
        self.p.set_checks_result(1)
        self.edit()
        res = self.hook(stdin="[]")
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertNotIn("Traceback", res.stderr)

    def test_checks_output_files_do_not_defeat_cache(self):
        self.p.set_checks_script(CHECKS_SH.replace("exit ", "echo x > build-out.txt\nexit ", 1))
        self.edit()
        for _ in range(3):
            res = self.hook()
            self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.p.checks_runs(), 1)

    def test_repo_without_commits_runs_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = InstalledProject(tmp, commit=False)
            res = p.run("stop-hook", stdin="{}")
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(p.checks_runs(), 1)
            p.set_checks_result(1)
            p.write("AGENTS.md", "# Agents\nedit\n")
            res = p.run("stop-hook", stdin="{}")
            self.assertEqual(res.returncode, 2, res.stderr)
            self.assertEqual(p.checks_runs(), 2)

    def test_slow_checks_time_out_without_blocking(self):
        self.p.set_checks_script("#!/usr/bin/env bash\nsleep 5\n")
        self.edit()
        start = time.monotonic()
        res = self.hook(FACTORY_STOP_HOOK_TIMEOUT="1")
        self.assertLess(time.monotonic() - start, 4)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("took over 1 s; not blocking", res.stderr)
        self.assertFalse((self.p.git_dir / STAMP).exists())

    def test_commit_after_failure_does_not_bypass(self):
        self.p.set_checks_result(1)
        self.edit()
        self.assertEqual(self.hook().returncode, 2)
        self.assertTrue((self.p.git_dir / FAILED).is_file())
        self.p.commit_all("fix attempt")
        res = self.hook()
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertEqual(self.p.checks_runs(), 2)

    def test_pass_clears_failure_marker(self):
        self.p.set_checks_result(1)
        self.edit()
        self.hook()
        self.p.set_checks_result(0)
        self.assertEqual(self.hook().returncode, 0)
        self.assertFalse((self.p.git_dir / FAILED).exists())
        self.p.commit_all("done")
        self.hook()
        self.assertEqual(self.p.checks_runs(), 2)

    def test_non_utf8_checks_output_does_not_crash(self):
        self.p.set_checks_script("#!/usr/bin/env bash\nprintf '\\377\\376 bad\\n'\nexit 1\n")
        self.edit()
        res = self.hook()
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertNotIn("Traceback", res.stderr)


if __name__ == "__main__":
    unittest.main()
