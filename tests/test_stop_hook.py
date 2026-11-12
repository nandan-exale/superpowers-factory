import json
import tempfile
import unittest

from installed_project import InstalledProject

STAMP = "factory-stop-hook.pass"


class StopHookTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p = InstalledProject(tmp.name)

    def hook(self, payload=None, stdin=None):
        return self.p.run("stop-hook", stdin=stdin if stdin is not None else json.dumps(payload or {}))

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


if __name__ == "__main__":
    unittest.main()
