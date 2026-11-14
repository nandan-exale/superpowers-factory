"""Tests for scripts/check and scripts/check-hook, run on copies of this repo."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "scripts" / "check"
HOOK = REPO / "scripts" / "check-hook"
CONFIG = "vendor/factory/factory/config.json"


def git(cwd, *args):
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return res.stdout


def copy_repo(dest):
    """Copy the working-tree version of every tracked file into a new, committed git repo."""
    for rel in git(REPO, "ls-files", "-z").split("\0"):
        src = REPO / rel
        if not rel or not src.is_file():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    git(dest, "init", "-q")
    git(dest, "add", "-A")
    git(dest, "-c", "user.email=test@example.com", "-c", "user.name=test",
        "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "copy")
    return dest


class RepoCopyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = copy_repo(Path(tmp.name))

    def edit(self, rel, change):
        path = self.root / rel
        path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")

    def edit_config(self, change):
        path = self.root / CONFIG
        cfg = json.loads(path.read_text(encoding="utf-8"))
        change(cfg)
        path.write_text(json.dumps(cfg), encoding="utf-8")


class CheckTest(RepoCopyTest):
    def run_check(self, *extra):
        res = subprocess.run(
            [sys.executable, str(CHECK), "--fast", "--root", str(self.root), *extra],
            capture_output=True, text=True,
        )
        return res.returncode, res.stdout

    def refresh_hashes(self):
        """List the copy's edited vendored files, as scripts/known-hashes does after a vendored edit."""
        subprocess.run([sys.executable, str(REPO / "scripts" / "known-hashes"), "--root", str(self.root)],
                       capture_output=True, check=True)

    def assertFails(self, name, needle, *extra):
        code, out = self.run_check(*extra)
        self.assertEqual(code, 1, out)
        self.assertIn(f"FAIL {name}: ", out)
        self.assertIn(needle, out)

    def test_clean_copy_passes(self):
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAIL", out)
        self.assertIn("PASS license", out)

    def test_mismatched_plugin_and_marketplace_versions_fail(self):
        def change(text):
            data = json.loads(text)
            data["plugins"][0]["version"] = "9.9.9"
            return json.dumps(data, indent=2) + "\n"
        self.edit(".claude-plugin/marketplace.json", change)
        self.assertFails("json", "marketplace.json version 9.9.9")

    def test_stale_known_hashes_fail(self):
        self.edit("vendor/factory/factory/bin/gate", lambda text: text + "# edited\n")
        self.assertFails("hashes", "factory/bin/gate")

    def test_syntax_error_in_stop_hook_fails(self):
        self.edit("vendor/factory/factory/bin/stop-hook", lambda text: text + "\ndef broken(:\n")
        self.assertFails("compile", "bin/stop-hook:")

    def test_missing_notice_fails(self):
        (self.root / "vendor/factory/NOTICE").unlink()
        self.assertFails("license", "vendor/factory/NOTICE is missing or empty")

    def test_missing_skill_source_fails(self):
        (self.root / "skills/agents-best-practices/SOURCE").unlink()
        self.assertFails("license", "skills/agents-best-practices/SOURCE is missing or empty")

    def test_unparseable_config_fails(self):
        self.edit(CONFIG, lambda text: text + "}")
        self.assertFails("json", "vendor/factory/factory/config.json")

    def test_unknown_model_alias_fails(self):
        self.edit_config(lambda cfg: cfg["routing"]["low"]["builder"].update(model="gpt"))
        self.assertFails("config", "routing.low.builder: model 'gpt' not in model_aliases")

    def test_unknown_effort_fails(self):
        self.edit_config(lambda cfg: cfg["surface_reviewers"]["ui"]["ux"].update(effort="huge"))
        self.assertFails("config", "surface_reviewers.ui.ux: effort 'huge' not in effort_levels")

    def test_intake_entry_checked(self):
        self.edit_config(lambda cfg: cfg["agents"].update(intake="fable"))
        self.assertFails("config", "agents.intake: expected an object with model and effort")

    def test_agent_with_model_fails(self):
        self.edit("vendor/factory/factory/agents/builder.md",
                  lambda text: text.replace("name: builder\n", "name: builder\nmodel: opus\n", 1))
        self.assertFails("frontmatter", "vendor/factory/factory/agents/builder.md: sets model")

    def test_skill_missing_description_fails(self):
        self.edit("skills/factory-install/SKILL.md",
                  lambda text: "\n".join(l for l in text.splitlines() if not l.startswith("description:")) + "\n")
        self.assertFails("frontmatter", "skills/factory-install/SKILL.md: missing description")

    def test_file_without_frontmatter_fails(self):
        self.edit("vendor/factory/factory/agents/intake.md", lambda text: "no frontmatter\n" + text)
        self.assertFails("frontmatter", "vendor/factory/factory/agents/intake.md: no --- frontmatter block")

    def test_nested_model_key_is_ignored(self):
        self.edit("vendor/factory/factory/agents/approver.md",
                  lambda text: text.replace("access:", "extra:\n  model: nested\naccess:", 1))
        self.refresh_hashes()
        code, out = self.run_check()
        self.assertEqual(code, 0, out)

    def test_syntax_error_in_route_fails(self):
        self.edit("vendor/factory/factory/bin/route", lambda text: text + "\ndef broken(:\n")
        self.assertFails("compile", "bin/route:")

    def test_bash_syntax_error_in_checks_fails(self):
        self.edit("vendor/factory/factory/checks.sh", lambda text: text + "\nif then\n")
        self.assertFails("compile", "checks.sh:")

    PROBE_HASH = "71bede1bb2ef6494d196e5e2be06c68e0f5352cd3018a4f44179dfbcc21dac5f"

    def test_forbidden_token_fails(self):
        self.edit("README.md", lambda text: text + "\nSee Harness" + "Probe.example for more.\n")
        self.assertFails("branding", "README.md: contains a forbidden upstream name",
                         "--extra-forbidden-hash", self.PROBE_HASH)

    def test_token_inside_longer_word_passes(self):
        # the design docs name the probe token in prose; drop them so only the edit is under test
        shutil.rmtree(self.root / "docs")
        self.edit("README.md", lambda text: text + "\nharnessprobes\n")
        code, out = self.run_check("--extra-forbidden-hash", self.PROBE_HASH)
        self.assertEqual(code, 0, out)

    def test_not_a_git_repo_reports_git_error(self):
        shutil.rmtree(self.root / ".git")
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL branding: RuntimeError: git ls-files failed", out)
        self.assertIn("not a git repository", out)

    def test_bom_does_not_hide_frontmatter(self):
        self.edit("vendor/factory/factory/agents/intake.md", lambda text: "\ufeff" + text)
        self.refresh_hashes()
        code, out = self.run_check()
        self.assertEqual(code, 0, out)

    def test_unreadable_file_does_not_hide_other_problems(self):
        (self.root / "vendor/factory/factory/agents/intake.md").write_bytes(b"\xff\xfe---")
        self.edit("vendor/factory/factory/agents/builder.md",
                  lambda text: text.replace("name: builder\n", "name: builder\nmodel: x\n", 1))
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("agents/intake.md: unreadable", out)
        self.assertIn("agents/builder.md: sets model", out)

    def append_to(self, rel, code):
        self.edit(rel, lambda text: text + "\n" + code)
        self.refresh_hashes()

    def test_unguarded_systemctl_fails(self):
        doctor = "vendor/factory/factory/bin/doctor"
        self.edit(doctor, lambda text: text.replace('shutil.which("systemctl")', "None"))
        self.append_to(doctor, 'subprocess.run(["systemctl", "x"])\n')
        self.assertFails("external-binaries", "shutil.which('systemctl')")

    def test_unguarded_binary_message_names_file_line_and_remedy(self):
        self.append_to("vendor/factory/factory/bin/doctor", 'subprocess.run(["nonexistent-tool", "x"])\n')
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"FAIL external-binaries: vendor/factory/factory/bin/doctor:\d+: 'nonexistent-tool'")
        self.assertIn("shutil.which('nonexistent-tool')", out)
        self.assertIn("die(", out)

    def test_guarded_binary_passes(self):
        self.append_to("vendor/factory/factory/bin/doctor",
                       'subprocess.run(["nonexistent-tool", "x"])\nshutil.which("nonexistent-tool")\n')
        code, out = self.run_check()
        self.assertEqual(code, 0, out)

    def test_git_and_bash_are_baseline(self):
        self.append_to("vendor/factory/factory/bin/doctor",
                       'subprocess.run(["git", "status"])\nsubprocess.run(["bash", "-c", "true"])\n')
        code, out = self.run_check()
        self.assertEqual(code, 0, out)

    def test_variable_and_computed_heads_are_ignored(self):
        self.append_to("vendor/factory/factory/bin/doctor",
                       'subprocess.run([tool, "x"])\nsubprocess.run([sys.executable, "x"])\n'
                       'subprocess.run(cmd)\nsubprocess.run([*argv])\n')
        code, out = self.run_check()
        self.assertEqual(code, 0, out)

    def test_unguarded_binary_in_lib_fails(self):
        self.append_to("vendor/factory/factory/lib/orchestrator/loop.py",
                       'subprocess.check_output(("nonexistent-tool",))\n')
        self.assertFails("external-binaries", "shutil.which('nonexistent-tool')")

    def test_orchestrate_without_which_fails(self):
        path = "vendor/factory/factory/bin/orchestrate"
        self.edit(path, lambda text: text.replace("shutil.which", "shutil.where"))
        self.refresh_hashes()
        self.assertFails("external-binaries", "orchestrate must check shutil.which")

    def test_missing_orchestrate_skips_the_popen_rule(self):
        (self.root / "vendor/factory/factory/bin/orchestrate").unlink()
        code, out = self.run_check()
        self.assertNotIn("orchestrate must check shutil.which", out)


class CheckHookTest(RepoCopyTest):
    def run_hook(self, payload=None, cwd=None, hook=HOOK, stdin=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(CHECK_HOOK_FAST="1", CLAUDE_PROJECT_DIR=str(cwd or self.root))
        res = subprocess.run([sys.executable, str(hook)],
                             input=json.dumps(payload or {}) if stdin is None else stdin,
                             capture_output=True, text=True, env=env)
        return res.returncode, res.stderr

    def test_clean_tree_skips(self):
        (self.root / "vendor/factory/NOTICE").write_text("")
        git(self.root, "-c", "user.email=t@e.com", "-c", "user.name=t",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
            "commit", "-qam", "empty notice")
        code, err = self.run_hook()
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")

    def test_dirty_passing_tree_allows_stop(self):
        self.edit("README.md", lambda text: text + "\nmore\n")
        code, err = self.run_hook()
        self.assertEqual(code, 0, err)

    def test_dirty_failing_tree_blocks(self):
        (self.root / "vendor/factory/NOTICE").unlink()
        code, err = self.run_hook()
        self.assertEqual(code, 2)
        self.assertIn("FAIL license: vendor/factory/NOTICE is missing or empty", err)

    def test_second_stop_does_not_block_again(self):
        (self.root / "vendor/factory/NOTICE").unlink()
        code, err = self.run_hook({"stop_hook_active": True})
        self.assertEqual(code, 0)
        self.assertIn("FAIL license", err)

    def test_outside_git_repo_does_not_block(self):
        with tempfile.TemporaryDirectory() as outside:
            code, err = self.run_hook(cwd=outside)
        self.assertEqual(code, 0)
        self.assertIn("not a git repository", err)

    def test_crashed_check_does_not_block(self):
        (self.root / "scripts/check").write_text("import sys\nsys.exit('boom')\n")
        code, err = self.run_hook(hook=self.root / "scripts/check-hook")
        self.assertEqual(code, 0, err)
        self.assertIn("crashed", err)
        self.assertIn("boom", err)

    def test_non_dict_payload_is_ignored(self):
        (self.root / "vendor/factory/NOTICE").unlink()
        code, err = self.run_hook(stdin="[]")
        self.assertEqual(code, 2, err)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
