import json
import shutil
import tempfile
import unittest

from installed_project import LABELS, InstalledProject

CHECK_NAMES = ("config", "agents", "files", "gitignore", "stop-hook", "claude-md", "labels")


class DoctorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p = InstalledProject(tmp.name)

    def doctor(self, *args, gh=True):
        return self.p.run("doctor", *args, gh=gh)

    def assertFails(self, name, needle, *args):
        res = self.doctor("--fast", *args)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn(f"FAIL {name}: ", res.stdout)
        self.assertIn(needle, res.stdout)

    def edit(self, rel, change):
        path = self.p.root / rel
        path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")

    def test_invalid_budget_fails(self):
        def change(text):
            cfg = json.loads(text)
            cfg["budgets"]["daily_usd"] = -1
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "budgets.daily_usd must be a positive number or null")

    def test_missing_budgets_fails(self):
        def change(text):
            cfg = json.loads(text)
            del cfg["budgets"]
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "budgets missing")

    def test_healthy_install_passes(self):
        res = self.doctor("--fast")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        for name in CHECK_NAMES:
            self.assertIn(f"PASS {name}\n", res.stdout)
        self.assertNotIn("checks", res.stdout)

    def test_full_run_includes_checks(self):
        res = self.doctor()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("PASS checks\n", res.stdout)

    def test_failing_checks_fail(self):
        self.p.set_checks_result(3)
        res = self.doctor()
        self.assertEqual(res.returncode, 1)
        self.assertIn("FAIL checks: factory/checks.sh exited 3", res.stdout)
        self.assertIn("checks output line", res.stdout)

    def test_unknown_model_alias_fails(self):
        def change(text):
            cfg = json.loads(text)
            cfg["routing"]["low"]["builder"]["model"] = "gpt"
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "routing.low.builder: model 'gpt' not in model_aliases")

    def test_agent_with_model_fails(self):
        self.edit(".claude/agents/builder.md", lambda t: t.replace("name: builder\n", "name: builder\nmodel: opus\n", 1))
        self.assertFails("agents", ".claude/agents/builder.md: sets model")

    def test_unexpected_frontmatter_key_fails(self):
        self.edit(".claude/agents/approver.md", lambda t: t.replace("name: approver\n", "name: approver\ncolor: red\n", 1))
        self.assertFails("agents", ".claude/agents/approver.md: unexpected frontmatter key 'color'")

    def test_missing_agent_fails(self):
        (self.p.root / ".claude/agents/reviewer-ui.md").unlink()
        self.assertFails("agents", ".claude/agents/reviewer-ui.md missing")

    def test_non_executable_script_fails(self):
        (self.p.root / "factory/bin/route").chmod(0o644)
        self.assertFails("files", "factory/bin/route is not executable")

    def test_missing_gitignore_entry_fails(self):
        self.p.write(".gitignore", "/factory/jobs/\n")
        self.assertFails("gitignore", ".worktrees/ is not gitignored")

    def test_missing_stop_hook_fails(self):
        self.p.write(".claude/settings.json", "{}\n")
        self.assertFails("stop-hook", "no Stop hook in .claude/settings.json runs factory/bin/stop-hook")

    def test_claude_md_without_import_fails(self):
        self.p.write("CLAUDE.md", "# Claude\n")
        self.assertFails("claude-md", "CLAUDE.md doesn't import AGENTS.md")

    def test_only_claude_md_passes(self):
        (self.p.root / "AGENTS.md").unlink()
        self.p.write("CLAUDE.md", "# Claude\n")
        res = self.doctor("--fast")
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_symlinked_claude_md_passes(self):
        (self.p.root / "CLAUDE.md").unlink()
        (self.p.root / "CLAUDE.md").symlink_to("AGENTS.md")
        res = self.doctor("--fast")
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("PASS claude-md\n", res.stdout)

    def test_bom_in_settings_and_claude_md_is_ok(self):
        for rel in (".claude/settings.json", "CLAUDE.md"):
            path = self.p.root / rel
            path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        res = self.doctor("--fast")
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_missing_label_fails(self):
        self.p.set_labels([name for name in LABELS if name != "factory:planned"])
        self.assertFails("labels", "label 'factory:planned' missing")

    @unittest.skipIf(shutil.which("gh", path="/usr/bin:/bin"), "a real gh is in /usr/bin or /bin")
    def test_missing_gh_warns(self):
        res = self.doctor("--fast", gh=False)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("WARN labels: gh not found; labels not checked", res.stdout)


if __name__ == "__main__":
    unittest.main()
