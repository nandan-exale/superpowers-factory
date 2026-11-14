import json
import os
import shutil
import sys
import tempfile
import unittest

from installed_project import LABELS, VENDOR, InstalledProject, load_script

CHECK_NAMES = ("config", "runtime", "agents", "files", "gitignore", "stop-hook", "claude-md", "labels", "paused",
               "runner")
# Prints $FAKE_<NAME>_VERSION for --version and exits $FAKE_<NAME>_EXIT (default 0).
FAKE_CLI = """#!{python}
import os, sys
name = os.path.basename(sys.argv[0]).upper().replace("-", "_")
sys.stdout.write(os.environ.get(f"FAKE_{{name}}_VERSION", "{version}\\n"))
sys.exit(int(os.environ.get(f"FAKE_{{name}}_EXIT", "0")))
"""
DENY_NOTE = ("runner-settings.json's deny rules (secret files, force pushes) bind only Claude Code; "
             "{name} agents aren't held to them")


class DoctorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p = InstalledProject(tmp.name)
        self.fake_cli("claude", "2.1.300 (Claude Code)")

    def fake_cli(self, binary, version):
        """An agent CLI in toolbin, which is on PATH with or without gh."""
        path = self.p.toolbin / binary
        path.write_text(FAKE_CLI.format(python=sys.executable, version=version))
        path.chmod(0o755)

    def use_runtime(self, name, **budgets):
        """runtime: <name> with every tier set, so config passes."""
        def change(text):
            cfg = json.loads(text)
            cfg["runtime"] = name
            cfg["runtimes"][name]["tiers"] = {t: "m1" for t in ("fast", "balanced", "strong", "frontier")}
            cfg["budgets"].update(budgets)
            return json.dumps(cfg)
        self.edit("factory/config.json", change)

    def doctor(self, *args, gh=True):
        return self.p.run("doctor", *args, gh=gh)

    def assertFails(self, name, needle, *args, env=None):
        res = self.p.run("doctor", "--fast", *args, env=env)
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
        (self.p.root / "factory/agents/learner.md").unlink()
        self.assertFails("agents", "factory/agents/learner.md missing")

    def test_bad_learning_config_fails(self):
        def change(text):
            cfg = json.loads(text)
            cfg["learning"]["tags"] = []
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "learning.tags")

    def test_old_learner_model_entry_fails(self):
        def change(text):
            cfg = json.loads(text)
            cfg["agents"]["learner"] = {"model": "opus", "effort": "high"}
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "agents.learner: model 'opus' is the old shape; use tier")

    def test_unknown_runtime_fails(self):
        def change(text):
            cfg = json.loads(text)
            cfg["runtime"] = "nope"
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "runtime 'nope' has no runtimes.nope")

    def test_runtime_without_the_tiers_routing_uses_fails(self):
        def change(text):
            cfg = json.loads(text)
            cfg["runtime"] = "codex"
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "runtimes.codex.tiers.strong isn't set")

    def test_missing_runtime_cli_fails(self):
        self.use_runtime("codex")
        path = os.pathsep.join((str(self.p.fakebin), str(self.p.toolbin), "/usr/bin", "/bin"))
        self.assertFails("runtime", "codex not found on PATH", env={"PATH": path})

    def test_runtime_cli_whose_version_fails_fails(self):
        self.use_runtime("codex")
        self.fake_cli("codex", "codex 0.9.0")
        self.assertFails("runtime", "codex --version failed", env={"FAKE_CODEX_EXIT": "3"})

    def test_other_runtime_warns_that_deny_rules_bind_only_claude(self):
        self.use_runtime("codex")
        self.fake_cli("codex", "codex 0.9.0")
        out = self.doctor("--fast").stdout
        self.assertNotIn("FAIL runtime", out)
        self.assertIn("WARN runtime: " + DENY_NOTE.format(name="codex"), out)

    def test_claude_runtime_passes_without_warnings(self):
        self.assertIn("PASS runtime\n", self.doctor("--fast").stdout)

    def test_runtime_without_cost_and_run_caps_warns(self):
        self.use_runtime("cursor", job_runs=None)
        self.fake_cli("cursor-agent", "2026.11.01")
        self.assertIn("WARN runtime: cursor reports no cost; set budgets.job_runs and budgets.daily_runs",
                      self.doctor("--fast").stdout)

    def test_runtime_without_cost_but_with_run_caps_is_quiet_about_cost(self):
        self.use_runtime("cursor", job_runs=40, daily_runs=150)
        self.fake_cli("cursor-agent", "2026.11.01")
        self.assertNotIn("reports no cost", self.doctor("--fast").stdout)

    def test_other_runtime_needs_no_stop_hook(self):
        self.use_runtime("opencode")
        self.fake_cli("opencode", "1.0.0")
        self.p.write(".claude/settings.json", "{}\n")
        self.assertIn("PASS stop-hook\n", self.doctor("--fast").stdout)

    def test_other_runtime_needs_the_section_in_agents_md(self):
        self.use_runtime("codex")
        self.fake_cli("codex", "codex 0.9.0")
        self.p.write("CLAUDE.md", "@AGENTS.md\n\n## Software factory\n\nx\n")
        self.assertFails("claude-md", "codex reads AGENTS.md; move the Software factory section there")

    def test_other_runtime_with_the_section_in_agents_md_passes(self):
        self.use_runtime("codex")
        self.fake_cli("codex", "codex 0.9.0")
        self.p.write("AGENTS.md", "# Agents\n\n## Software factory\n\nx\n")
        self.assertIn("PASS claude-md\n", self.doctor("--fast").stdout)

    def test_doctor_never_looks_for_recorded_fixtures(self):
        self.use_runtime("copilot", job_runs=40, daily_runs=150)
        self.fake_cli("copilot", "1.0.0")
        self.assertNotIn("fixture", self.doctor("--fast").stdout)

    @unittest.skipUnless(sys.platform == "darwin", "Keychain only; Linux tokens are in test_runner_linux")
    def test_other_runtime_keychain_item_is_named_for_it(self):
        self.use_runtime("codex")
        self.fake_cli("codex", "codex 0.9.0")
        out = self.p.run("doctor", "--fast", env={"FAKE_SECURITY_EXIT": "44"}).stdout
        self.assertIn("WARN runner: no Keychain item factory-codex-token", out)

    @unittest.skipUnless(sys.platform == "darwin", "Keychain only; Linux tokens are in test_runner_linux")
    def test_copilot_needs_no_keychain_item(self):
        self.use_runtime("copilot", job_runs=40, daily_runs=150)
        self.fake_cli("copilot", "1.0.0")
        out = self.p.run("doctor", "--fast", env={"FAKE_SECURITY_EXIT": "44"}).stdout
        self.assertNotIn("Keychain", out)

    def test_bad_run_cap_fails(self):
        def change(text):
            cfg = json.loads(text)
            cfg["budgets"]["daily_runs"] = 2.5
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "budgets.daily_runs must be a positive integer or null")

    def test_missing_revert_and_risk_ok_labels_fail(self):
        self.p.set_labels([n for n in LABELS if n not in ("factory:revert", "factory:risk-ok")])
        res = self.p.run("doctor", "--fast")
        self.assertIn("label 'factory:revert' missing", res.stdout)
        self.assertIn("label 'factory:risk-ok' missing", res.stdout)

    def test_paused_is_a_warning_with_the_reason(self):
        self.p.write("factory/jobs/paused.json", json.dumps({"reason": "main is red", "time": "t"}))
        self.assertIn("WARN paused: main is red", self.p.run("doctor", "--fast").stdout)

    def test_bad_safety_config_fails(self):
        cfg = json.loads((self.p.root / "factory/config.json").read_text())
        cfg.update(watch={"enabled": 1, "max_minutes": 0, "ignore_workflows": "x"}, risky_paths="x",
                   secret_scan={"allow": [1]})
        self.p.write("factory/config.json", json.dumps(cfg))
        out = self.p.run("doctor", "--fast").stdout
        for text in ("watch.enabled", "watch.max_minutes", "watch.ignore_workflows", "risky_paths",
                     "secret_scan.allow"):
            self.assertIn(text, out)

    def test_bad_handoff_cap_fails(self):
        for cap in (0, "8", True):
            def change(text, cap=cap):
                cfg = json.loads(text)
                cfg["handoff"] = {"max_tasks_per_part": cap}
                return json.dumps(cfg)
            self.edit("factory/config.json", change)
            self.assertFails("config", "handoff.max_tasks_per_part must be a positive integer")

    def test_config_without_handoff_passes(self):
        def change(text):
            cfg = json.loads(text)
            cfg.pop("handoff", None)
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertIn("PASS config", self.doctor("--fast").stdout)

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

    @unittest.skipUnless(sys.platform == "darwin", "Keychain only; Linux tokens are in test_runner_linux")
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

    def test_unknown_tier_fails(self):
        def change(text):
            cfg = json.loads(text)
            cfg["routing"]["low"]["builder"]["tier"] = "huge"
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "routing.low.builder: tier 'huge' isn't one of fast, balanced, strong, frontier")

    def test_agent_with_model_fails(self):
        self.edit("factory/agents/builder.md", lambda t: t.replace("name: builder\n", "name: builder\nmodel: opus\n", 1))
        self.assertFails("agents", "factory/agents/builder.md: sets model")

    def test_unexpected_frontmatter_key_fails(self):
        self.edit("factory/agents/approver.md", lambda t: t.replace("name: approver\n", "name: approver\ncolor: red\n", 1))
        self.assertFails("agents", "factory/agents/approver.md: unexpected frontmatter key 'color'")

    def test_bad_access_fails(self):
        self.edit("factory/agents/reviewer-code.md", lambda t: t.replace("access: read\n", "access: maybe\n", 1))
        self.assertFails("agents", "factory/agents/reviewer-code.md: access must be read or write")

    def test_missing_agent_fails(self):
        (self.p.root / "factory/agents/reviewer-ui.md").unlink()
        self.assertFails("agents", "factory/agents/reviewer-ui.md missing")

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

    def set_notify(self, notify):
        cfg = json.loads((self.p.root / "factory/config.json").read_text())
        cfg["notify"] = notify
        self.p.write("factory/config.json", json.dumps(cfg))

    def test_bad_notify_config_fails(self):
        for notify in ({"command": "osascript"}, {"command": []}, {"command": ["say", 1]}, "say"):
            with self.subTest(notify=notify):
                self.set_notify(notify)
                self.assertFails("config", "notify.command must be a non-empty list of strings")

    def test_notify_program_not_found_warns(self):
        self.set_notify({"command": ["/nonexistent/notify-me", "hi"]})
        res = self.p.run("doctor", "--fast")
        self.assertIn("WARN config: notify.command: /nonexistent/notify-me not found", res.stdout)

    def test_valid_notify_config_says_nothing(self):
        self.set_notify({"command": [sys.executable, "-c", "pass"]})
        self.assertNotIn("notify", self.p.run("doctor", "--fast").stdout)


if __name__ == "__main__":
    unittest.main()
