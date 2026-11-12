import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import factory_files as ff  # noqa: E402

HOOK = REPO / "hooks/factory-session"
STATE = REPO / "bin/factory-state"


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "FACTORY_", "CLAUDE_"))}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", **extra)
    return env


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          env=clean_env(), check=True).stdout


class SessionHookTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "project"
        self.root.mkdir()
        git(self.root, "init", "-q")
        git(self.root, "remote", "add", "origin", "https://github.com/o/r.git")

    def install(self, manifest=True):
        for rel in ff.FILES:
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ff.VENDOR / rel, target)
        if manifest:
            (self.root / ff.MANIFEST).write_text(json.dumps(ff.manifest_data()))

    def hook(self, **env):
        env.setdefault("CLAUDE_PROJECT_DIR", str(self.root))
        res = subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True, text=True,
                             env=clean_env(**env))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stderr, "")
        if not res.stdout.strip():
            return None
        out = json.loads(res.stdout)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        return out["hookSpecificOutput"]["additionalContext"]

    def test_not_a_git_repo_is_silent(self):
        shutil.rmtree(self.root / ".git")
        self.assertIsNone(self.hook())

    def test_non_github_origin_is_silent(self):
        git(self.root, "remote", "set-url", "origin", "https://gitlab.com/o/r.git")
        self.assertIsNone(self.hook())

    def test_not_installed_offers_install_once(self):
        text = self.hook()
        self.assertIn("/factory-install", text)
        self.assertIn(f'"{STATE}" decline', text)
        self.assertNotIn("/factory-update", text)

    def test_declined_is_silent(self):
        res = subprocess.run([sys.executable, str(STATE), "decline"], cwd=self.root,
                             capture_output=True, text=True, env=clean_env())
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIsNone(self.hook())
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    def test_reset_brings_the_offer_back(self):
        for cmd in ("decline", "reset"):
            subprocess.run([sys.executable, str(STATE), cmd], cwd=self.root, env=clean_env(), check=True)
        self.assertIn("/factory-install", self.hook())

    def test_missing_manifest_offers_update_and_option_3(self):
        self.install(manifest=False)
        text = self.hook()
        self.assertIn("/factory-update", text)
        self.assertIn("3. Factory", text)

    def test_stale_manifest_offers_update(self):
        self.install()
        data = json.loads((self.root / ff.MANIFEST).read_text())
        data["vendor_hash"] = "0" * 64
        (self.root / ff.MANIFEST).write_text(json.dumps(data))
        self.assertIn("/factory-update", self.hook())

    def test_current_install_offers_option_3_only(self):
        self.install()
        text = self.hook()
        self.assertIn("3. Factory", text)
        self.assertIn("/factory-handoff", text)
        self.assertNotIn("/factory-update", text)
        self.assertNotIn("/factory-install", text)

    def test_unreadable_manifest_counts_as_outdated(self):
        self.install(manifest=False)
        (self.root / ff.MANIFEST).mkdir()
        self.assertIn("/factory-update", self.hook())

    def test_runner_session_is_silent(self):
        self.assertIsNone(self.hook(FACTORY_RUNNER="1"))
        self.install(manifest=False)
        self.assertIsNone(self.hook(FACTORY_RUNNER="1"))

    def test_decline_is_shared_with_linked_worktrees(self):
        git(self.root, "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false",
            "commit", "-q", "--allow-empty", "-m", "init")
        linked = self.root.parent / "linked"
        git(self.root, "worktree", "add", "-q", str(linked))
        self.assertIn("/factory-install", self.hook(CLAUDE_PROJECT_DIR=str(linked)))
        subprocess.run([sys.executable, str(STATE), "decline"], cwd=self.root, env=clean_env(), check=True,
                       capture_output=True)
        self.assertIsNone(self.hook(CLAUDE_PROJECT_DIR=str(linked)))
        subprocess.run([sys.executable, str(STATE), "reset"], cwd=linked, env=clean_env(), check=True,
                       capture_output=True)
        self.assertIn("/factory-install", self.hook())

    def test_only_the_github_host_counts(self):
        for url in ("https://notgithub.com/o/r.git", "https://github.com.evil.example/o/r.git",
                    "git@evilgithub.com:o/r.git", "https://evil.example/github.com/r.git",
                    "/srv/git/github.com/r.git"):
            git(self.root, "remote", "set-url", "origin", url)
            self.assertIsNone(self.hook(), url)

    def test_github_url_forms_are_recognised(self):
        for url in ("git@github.com:o/r.git", "ssh://git@github.com/o/r.git",
                    "ssh://git@github.com:22/o/r.git", "https://user@GitHub.com/o/r.git"):
            git(self.root, "remote", "set-url", "origin", url)
            self.assertIn("/factory-install", self.hook(), url)

    def test_internal_error_prints_nothing(self):
        self.install()
        self.assertIsNone(self.hook(FACTORY_VENDOR_DIR=str(self.root / "no-such-dir")))


if __name__ == "__main__":
    unittest.main()
