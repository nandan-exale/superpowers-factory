import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RELEASE = REPO / "scripts/release"

PLUGIN = '{\n  "name": "p",\n  "version": "0.2.0",\n  "keywords": ["a", "b"]\n}\n'
MARKET = '{\n  "name": "p",\n  "plugins": [ { "name": "p", "version": "0.2.0", "source": "./" } ]\n}\n'
CHANGELOG = "# Changelog\n\nIntro.\n\n## [0.2.0] - 2026-11-12\n\n### Added\n\n- old thing\n"
HASHES_STUB = ("import pathlib\npathlib.Path('vendor').mkdir(exist_ok=True)\n"
               "pathlib.Path('vendor/known-hashes.json').write_text('{}\\n')\n")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.origin = base / "origin.git"
        git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.root = base / "r"
        (self.root / ".claude-plugin").mkdir(parents=True)
        (self.root / "scripts").mkdir()
        (self.root / ".claude-plugin/plugin.json").write_text(PLUGIN)
        (self.root / ".claude-plugin/marketplace.json").write_text(MARKET)
        (self.root / "CHANGELOG.md").write_text(CHANGELOG)
        (self.root / "scripts/known-hashes").write_text(HASHES_STUB)
        self.set_check(0)
        shutil.copy(RELEASE, self.root / "scripts/release")
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "T")
        git(self.root, "config", "commit.gpgsign", "false")
        git(self.root, "config", "tag.gpgsign", "false")
        git(self.root, "remote", "add", "origin", str(self.origin))
        self.commit("chore: release 0.2.0")
        git(self.root, "tag", "-a", "v0.2.0", "-m", "Release 0.2.0")
        for subject in ("feat: add widget", "fix: stop crash", "docs: explain widget"):
            self.commit(subject)

    def set_check(self, code):
        (self.root / "scripts/check").write_text(f"import sys\nsys.exit({code})\n")

    def commit(self, subject):
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "--allow-empty", "-m", subject)

    def release(self, version):
        return subprocess.run([sys.executable, str(self.root / "scripts/release"), version],
                              cwd=self.root, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def test_release_bumps_both_versions_without_reformatting(self):
        res = self.release("0.3.0")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        plugin = (self.root / ".claude-plugin/plugin.json").read_text()
        self.assertEqual(plugin, PLUGIN.replace("0.2.0", "0.3.0"))
        market = json.loads((self.root / ".claude-plugin/marketplace.json").read_text())
        self.assertEqual(market["plugins"][0]["version"], "0.3.0")

    def test_changelog_groups_commits_since_the_last_tag(self):
        self.release("0.3.0")
        text = (self.root / "CHANGELOG.md").read_text()
        new = text[text.index("## [0.3.0] - "):text.index("## [0.2.0]")]
        self.assertIn("### Added\n\n- add widget\n", new)
        self.assertIn("### Fixed\n\n- stop crash\n", new)
        self.assertIn("### Changed\n\n- docs: explain widget\n", new)
        self.assertNotIn("release 0.2.0", new)
        self.assertLess(text.index("Intro."), text.index("## [0.3.0]"))

    def test_release_commits_and_tags_but_never_pushes(self):
        res = self.release("0.3.0")
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "chore: release 0.3.0")
        self.assertEqual(git(self.root, "tag", "--list", "v0.3.0"), "v0.3.0")
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        self.assertEqual(git(self.root, "ls-remote", "origin"), "")
        self.assertIn("git push origin main v0.3.0", res.stdout)

    def test_refuses_a_dirty_tree(self):
        (self.root / "x.txt").write_text("x\n")
        res = self.release("0.3.0")
        self.assertEqual(res.returncode, 1)
        self.assertIn("working tree", res.stderr)

    def test_refuses_a_version_that_is_not_higher(self):
        self.assertEqual(self.release("0.2.0").returncode, 1)
        self.assertEqual(self.release("0.1.9").returncode, 1)

    def test_refuses_a_malformed_version(self):
        self.assertEqual(self.release("1.0").returncode, 1)
        self.assertEqual(self.release("v1.0.0").returncode, 1)

    def test_failed_check_leaves_changes_uncommitted(self):
        self.set_check(1)
        self.commit("chore: failing check stub")
        head = git(self.root, "rev-parse", "HEAD")
        res = self.release("0.3.0")
        self.assertEqual(res.returncode, 1)
        self.assertIn("scripts/check failed", res.stderr)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.root, "tag", "--list", "v0.3.0"), "")
        self.assertIn("0.3.0", (self.root / ".claude-plugin/plugin.json").read_text())


if __name__ == "__main__":
    unittest.main()
