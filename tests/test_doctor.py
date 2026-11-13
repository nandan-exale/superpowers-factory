import json
import shutil
import tempfile
import unittest

from installed_project import LABELS, VENDOR, InstalledProject, load_script

CHECK_NAMES = ("config", "agents", "files", "gitignore", "stop-hook", "claude-md", "labels", "runner")


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

    def test_missing_manifest_fails(self):
        (self.p.root / "factory/manifest.json").unlink()
        self.assertFails("files", "factory/manifest.json missing")

    def test_missing_budgets_fails(self):
        def change(text):
            cfg = json.loads(text)
            del cfg["budgets"]
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "budgets missing")

    def test_missing_learning_label_fails(self):
        self.p.set_labels([name for name in LABELS if name != "factory:learning"])
        self.assertFails("labels", "label 'factory:learning' missing")

    def test_missing_learner_agent_fails(self):
        (self.p.root / ".claude/agents/learner.md").unlink()
        self.assertFails("agents", ".claude/agents/learner.md missing")

    def test_bad_learning_config_fails(self):
        def change(text):
            cfg = json.loads(text)
            cfg["learning"]["tags"] = []
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "learning.tags")

    def test_bad_learner_model_fails(self):
        def change(text):
            cfg = json.loads(text)
            cfg["agents"]["learner"]["model"] = "gpt"
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "agents.learner: model 'gpt' not in model_aliases")

    def runner_settings(self, change):
        path = self.p.root / "factory/runner-settings.json"
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    def test_runner_settings_without_sandbox_fail(self):
        self.runner_settings(lambda d: d["sandbox"].update(enabled=False))
        self.assertFails("runner", "factory/runner-settings.json: sandbox.enabled must be true")

    def test_runner_settings_missing_allow_rule_fail(self):
        self.runner_settings(lambda d: d["permissions"]["allow"].remove("Bash(gh *)"))
        self.assertFails("runner", "factory/runner-settings.json: missing allow rule Bash(gh *)")

    def test_runner_settings_with_escape_hatch_fail(self):
        self.runner_settings(lambda d: d["sandbox"].update(allowUnsandboxedCommands=True))
        self.assertFails("runner", "sandbox.allowUnsandboxedCommands must be false")

    def test_missing_keychain_item_warns(self):
        res = self.p.run("doctor", "--fast", env={"FAKE_SECURITY_EXIT": "44"})
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("WARN runner: no Keychain item factory-claude-token", res.stdout)

    def test_checks_run_without_claude_credentials(self):
        self.p.set_checks_script(
            "#!/usr/bin/env bash\nenv > \"$(git rev-parse --git-dir)/checks-env\"\n")
        secrets = {"CLAUDE_CODE_OAUTH_TOKEN": "tok", "ANTHROPIC_API_KEY": "key",
                   "ANTHROPIC_AUTH_TOKEN": "auth", "ANTHROPIC_BASE_URL": "http://x"}
        res = self.p.run("doctor", env=secrets)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        seen = (self.p.git_dir / "checks-env").read_text()
        self.assertIn("PATH=", seen)
        for name in secrets:
            self.assertNotIn(name, seen)

    def protection(self, **env):
        res = self.p.run("doctor", "--fast", env=env)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return res.stdout

    def test_protected_base_branch_passes(self):
        self.assertIn("PASS runner\n", self.protection())

    UNCONFIRMED = ("WARN runner: could not confirm branch protection for main (needs admin, "
                   "or uses rulesets without force-push/deletion rules)")
    RULES = json.dumps([{"type": "non_fast_forward"}, {"type": "deletion"}, {"type": "pull_request"}])

    def test_unprotected_base_branch_cannot_be_confirmed(self):
        out = self.protection(FAKE_GH_API_EXIT="1", FAKE_GH_API_ERR="gh: Branch not protected (HTTP 404)")
        self.assertIn(self.UNCONFIRMED, out)

    def test_rulesets_blocking_force_push_and_deletion_pass(self):
        out = self.protection(FAKE_GH_API_EXIT="1", FAKE_GH_API_ERR="gh: Not Found (HTTP 404)",
                              FAKE_GH_RULES_OUT=self.RULES)
        self.assertIn("PASS runner\n", out)

    def test_rulesets_with_only_one_rule_do_not_confirm(self):
        out = self.protection(FAKE_GH_API_EXIT="1", FAKE_GH_API_ERR="gh: Not Found (HTTP 404)",
                              FAKE_GH_RULES_OUT=json.dumps([{"type": "deletion"}]))
        self.assertIn(self.UNCONFIRMED, out)

    def test_rulesets_override_a_classic_answer_that_allows_force_push(self):
        out = self.protection(FAKE_GH_API_OUT=json.dumps(
            {"allow_force_pushes": {"enabled": True}, "allow_deletions": {"enabled": False}}),
            FAKE_GH_RULES_OUT=self.RULES)
        self.assertIn("PASS runner\n", out)

    def test_branch_allowing_force_push_warns(self):
        out = self.protection(FAKE_GH_API_OUT=json.dumps(
            {"allow_force_pushes": {"enabled": True}, "allow_deletions": {"enabled": False}}))
        self.assertIn("WARN runner: base branch main has no protection against force-push/deletion", out)

    def test_unreadable_protection_warns_without_failing(self):
        out = self.protection(FAKE_GH_API_EXIT="1", FAKE_GH_API_ERR="gh: Forbidden (HTTP 403)")
        self.assertIn(self.UNCONFIRMED, out)

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

    def test_missing_digest_label_fails(self):
        self.p.set_labels([name for name in LABELS if name != "factory:digest"])
        self.assertFails("labels", "label 'factory:digest' missing")

    def test_bad_digest_config_fails(self):
        cfg = json.loads((self.p.root / "factory/config.json").read_text())
        cfg["digest"] = {"enabled": "yes", "hour": 24, "days": 0}
        self.p.write("factory/config.json", json.dumps(cfg))
        res = self.p.run("doctor", "--fast")
        for text in ("digest.enabled must be true or false", "digest.hour must be an integer from 0 to 23",
                     "digest.days must be a positive integer"):
            self.assertIn(text, res.stdout)

    def test_missing_digest_config_is_fine(self):
        cfg = json.loads((self.p.root / "factory/config.json").read_text())
        cfg.pop("digest")
        self.p.write("factory/config.json", json.dumps(cfg))
        self.assertNotIn("digest", self.p.run("doctor", "--fast").stdout)


if __name__ == "__main__":
    unittest.main()
