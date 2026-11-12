"""Tests for scripts/check and scripts/check-hook, run on copies of this repo."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "scripts" / "check"
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
    git(dest, "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-q", "-m", "copy")
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

    def test_missing_notice_fails(self):
        (self.root / "vendor/factory/NOTICE").unlink()
        self.assertFails("license", "vendor/factory/NOTICE is missing or empty")

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
        self.edit("vendor/factory/.claude/agents/builder.md",
                  lambda text: text.replace("name: builder\n", "name: builder\nmodel: opus\n", 1))
        self.assertFails("frontmatter", "vendor/factory/.claude/agents/builder.md: sets model")

    def test_skill_missing_description_fails(self):
        self.edit("skills/factory-install/SKILL.md",
                  lambda text: "\n".join(l for l in text.splitlines() if not l.startswith("description:")) + "\n")
        self.assertFails("frontmatter", "skills/factory-install/SKILL.md: missing description")

    def test_file_without_frontmatter_fails(self):
        self.edit("vendor/factory/.claude/agents/intake.md", lambda text: "no frontmatter\n" + text)
        self.assertFails("frontmatter", "vendor/factory/.claude/agents/intake.md: no --- frontmatter block")

    def test_nested_model_key_is_ignored(self):
        self.edit("vendor/factory/.claude/agents/approver.md",
                  lambda text: text.replace("tools:", "extra:\n  model: nested\ntools:", 1))
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


if __name__ == "__main__":
    unittest.main()
