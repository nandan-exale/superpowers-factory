import contextlib
import http.server
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from installed_project import InstalledProject, clean_env, git, load_script


class CiCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.p = InstalledProject(self.tmp)
        self.origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.origin, "config", "receive.autogc", "false")
        git(self.p.root, "branch", "-M", "main")
        git(self.p.root, "remote", "add", "origin", str(self.origin))
        git(self.p.root, "config", "user.email", "ci@example.com")
        git(self.p.root, "config", "user.name", "ci")
        git(self.p.root, "push", "-q", "-u", "origin", "main")
        self.runner = load_script(f"runner_ci_{id(self)}", self.p.root / "factory/bin/runner")
        # The runner's git runs in this process too: no background gc or maintenance may outlive the test.
        env = mock.patch.dict(os.environ, clean_env(), clear=True)
        env.start()
        self.addCleanup(env.stop)

    def out(self, fn, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = fn(*args)
        return code, buf.getvalue()


class WorkflowTest(CiCase):
    def test_renders_schedule_permissions_steps_and_timeout(self):
        code, text = self.out(self.runner.cmd_workflow, "2.1.3")
        self.assertEqual(code, 0)
        _, runner = self.runner.load_config()
        for needle in ('cron: "' + self.runner.cron(runner["interval_minutes"]) + '"', "workflow_dispatch:",
                       "group: factory-runner", "cancel-in-progress: false", "contents: write", "issues: write",
                       "pull-requests: write", "actions: read", "actions/checkout@v4", "fetch-depth: 0",
                       "bubblewrap socat", "@anthropic-ai/claude-code@2.1.3", "factory/bin/runner tick --ci",
                       "secrets.FACTORY_CLAUDE_TOKEN", "secrets.FACTORY_GH_TOKEN",
                       f"timeout-minutes: {runner['max_minutes'] + 10}", "upload-artifact"):
            self.assertIn(needle, text)
        self.assertNotIn("\t", text)
        self.assertTrue(all((len(l) - len(l.lstrip(" "))) % 2 == 0 for l in text.splitlines()))

    def test_cron_has_a_15_minute_floor(self):
        self.assertEqual(self.runner.cron(5), "*/15 * * * *")
        self.assertEqual(self.runner.cron(30), "*/30 * * * *")
        self.assertEqual(self.runner.cron(120), "0 */2 * * *")

    def test_bad_version_is_refused(self):
        with self.assertRaises(SystemExit):
            self.out(self.runner.cmd_workflow, "latest")


class AskForCredentials(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="r"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_GET

    def log_message(self, *args):
        pass


class StateTest(CiCase):
    def call(self, fn):
        return fn(str(self.origin))

    def state_log(self):
        return git(self.tmp, "--git-dir", str(self.origin), "log", "--format=%H %P", "factory-state").splitlines()

    def state_files(self):
        return git(self.tmp, "--git-dir", str(self.origin), "ls-tree", "-r", "--name-only", "factory-state").split()

    def write(self, rel, text):
        path = self.p.root / "factory/jobs" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_first_save_creates_an_orphan_branch_without_locks_or_big_files(self):
        self.write("001-a/job.json", "{}")
        self.write("001-a/.lock", "")
        self.write("runs/big.json", "x" * 1_100_000)
        self.assertTrue(self.call(self.runner.restore_state))
        self.assertTrue(self.call(self.runner.save_state))
        self.assertEqual(self.state_files(), ["001-a/job.json"])
        (commit,) = self.state_log()
        self.assertEqual(commit.split(), commit.split()[:1])  # no parent: orphan
        self.assertEqual(git(self.p.root, "status", "--porcelain"), "")  # main's index untouched

    def test_second_save_appends_and_restore_brings_files_back(self):
        self.write("001-a/job.json", "{}")
        self.call(self.runner.restore_state)
        self.call(self.runner.save_state)
        import shutil
        shutil.rmtree(self.p.root / "factory/jobs")
        self.assertTrue(self.call(self.runner.restore_state))
        self.assertEqual((self.p.root / "factory/jobs/001-a/job.json").read_text(), "{}")
        self.write("002-b/job.json", "{}")
        self.call(self.runner.save_state)
        log = self.state_log()
        self.assertEqual(len(log), 2)
        self.assertEqual(log[0].split()[1], log[1].split()[0])  # new commit's parent is the old one

    def test_a_save_builds_on_whatever_origin_has_now(self):
        self.write("001-a/job.json", "{}")
        self.call(self.runner.restore_state)
        self.call(self.runner.save_state)
        self.call(self.runner.restore_state)
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", "-b", "factory-state", str(self.origin), str(other))
        (other / "elsewhere.txt").write_text("x")
        git(other, "add", "elsewhere.txt")
        git(other, "-c", "user.email=o@e.com", "-c", "user.name=o", "commit", "-q", "-m", "someone else")
        git(other, "push", "-q", "origin", "factory-state")
        self.write("002-b/job.json", "{}")
        self.assertTrue(self.call(self.runner.save_state))
        newest, parent = self.state_log()[0].split()
        self.assertEqual(parent, git(other, "rev-parse", "HEAD").strip())
        self.assertIn("002-b/job.json", self.state_files())

    def test_a_rejected_push_is_fetched_rebuilt_and_retried_once(self):
        hook = self.origin / "hooks" / "pre-receive"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text(f"#!/bin/sh\n[ -e {self.tmp}/seen ] && exit 0\ntouch {self.tmp}/seen\nexit 1\n")
        hook.chmod(0o755)
        self.write("001-a/job.json", "{}")
        self.assertTrue(self.call(self.runner.save_state))
        self.assertTrue((self.tmp / "seen").exists())
        self.assertEqual(self.state_files(), ["001-a/job.json"])
        hook.write_text("#!/bin/sh\nexit 1\n")
        self.assertFalse(self.call(self.runner.save_state))  # rejected twice

    def test_restore_refuses_unsafe_paths(self):
        bad = self.tmp / "bad.tar"
        with tarfile.open(bad, "w") as tar:
            info = tarfile.TarInfo("../escape.txt")
            info.size = 0
            tar.addfile(info, io.BytesIO(b""))
        with self.assertRaises(ValueError):
            self.runner.extract_state(bad.read_bytes(), self.p.root / "factory/jobs")

    def test_symlinks_are_not_saved(self):
        secret = self.tmp / "outside.txt"
        secret.write_text("not job state")
        self.write("001-a/job.json", "{}")
        (self.p.root / "factory/jobs/001-a/link").symlink_to(secret)
        self.assertEqual(self.runner.state_files(), ["001-a/job.json"])
        self.assertIsNone(self.runner.read_state_file("001-a/link"))

    def test_odd_file_names_are_saved_as_they_are(self):
        for name in ('a "quoted" name.md', "back\\slash.md", "new\nline.md", "caf\u00e9.md"):
            self.write(f"001-a/{name}", name)
        self.assertTrue(self.call(self.runner.save_state))
        import shutil
        shutil.rmtree(self.p.root / "factory/jobs")
        self.assertTrue(self.call(self.runner.restore_state))
        for name in ('a "quoted" name.md', "back\\slash.md", "new\nline.md", "caf\u00e9.md"):
            self.assertEqual((self.p.root / "factory/jobs/001-a" / name).read_text(), name)

    def plant(self, route, marker):
        """Config a session could leave in the checkout so that git run there executes `touch marker`.
        Returns the keys and sections to remove afterwards."""
        script = self.tmp / "evil"
        script.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
        script.chmod(0o755)
        if route == "filter clean":
            self.write(".gitattributes", "* filter=x\n")
            keys = {"filter.x.clean": f"touch {marker}; cat", "filter.x.smudge": f"touch {marker}; cat"}
        elif route == "credential helper":
            server = http.server.HTTPServer(("127.0.0.1", 0), AskForCredentials)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            keys = {"credential.helper": f"!touch {marker}", "protocol.allow": "always",
                    f"url.http://127.0.0.1:{server.server_port}/r.git.insteadOf": str(self.origin)}
        elif route == "ext:: via insteadOf":
            keys = {"protocol.allow": "always", f"url.ext::sh -c touch% {marker}% #.insteadOf": str(self.origin)}
        elif route == "core.gitProxy":
            keys = {"core.gitProxy": str(script), "url.git://example.invalid/r.insteadOf": str(self.origin)}
        else:  # core.alternateRefsCommand
            alternate = self.tmp / "alternate-objects"
            alternate.mkdir(exist_ok=True)
            (self.p.git_dir / "objects" / "info").mkdir(exist_ok=True)
            (self.p.git_dir / "objects" / "info" / "alternates").write_text(f"{alternate}\n")
            keys = {"core.alternateRefsCommand": f"touch {marker}"}
        for key, value in keys.items():
            git(self.p.root, "config", key, value)
        return keys

    ROUTES = ("filter clean", "credential helper", "ext:: via insteadOf", "core.gitProxy", "core.alternateRefsCommand")

    def test_no_route_in_the_checkout_runs_anything_during_save_or_restore(self):
        for route in self.ROUTES:
            with self.subTest(route=route):
                marker = self.tmp / f"ran-{route.split()[0]}"
                keys = self.plant(route, marker)
                self.write("001-a/job.json", json.dumps(route))
                self.assertTrue(self.call(self.runner.save_state))
                self.assertTrue(self.call(self.runner.restore_state))
                self.assertTrue(self.call(self.runner.save_state))  # a second save fetches a parent first
                self.assertFalse(marker.exists())
                self.assertEqual(git(self.tmp, "--git-dir", str(self.origin), "show", "factory-state:001-a/job.json"),
                                 json.dumps(route))
                for key in keys:
                    git(self.p.root, "config", "--unset", key)

    def test_state_git_reads_no_config_from_the_checkout(self):
        for route in self.ROUTES:
            self.plant(route, self.tmp / "ran")
        with self.runner.state_repo(str(self.origin)) as g:
            shown = g("config", "--list", "--show-origin").stdout.decode()
            git_dir = g("rev-parse", "--absolute-git-dir").stdout.decode().strip()
        self.assertNotIn(str(self.p.root), shown)
        self.assertNotIn(str(self.p.root), git_dir)
        for key in ("filter.", "credential.", "gpg.", "core.gitproxy", "core.alternaterefscommand", "url.",
                    "protocol.allow=always"):
            self.assertNotIn(key, shown)
        self.assertIn("protocol.allow=never", shown)

    def test_github_token_authenticates_an_https_origin_only(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "pat-123"}):
            auth = self.runner.state_auth("https://github.com/o/r")
            self.assertEqual(list(auth), ["http.https://github.com/o/r.extraheader"])
            self.assertTrue(auth["http.https://github.com/o/r.extraheader"].startswith("AUTHORIZATION: basic "))
            self.assertEqual(self.runner.state_auth(str(self.origin)), {})
        self.assertEqual(self.runner.state_auth("https://github.com/o/r"), {})

    def test_risky_local_key_flags_transport_proxy_and_url_rewrites(self):
        for key, value in (("protocol.allow", "always"), ("url.ext::sh.insteadof", "x"),
                           ("url.https://example.com/.pushinsteadof", "git@example.com:"),
                           ("remote.origin.pushurl", "ext::sh -c true"), ("remote.origin.vcs", "x"),
                           ("core.gitproxy", "/bin/true"), ("core.alternaterefscommand", "true")):
            with self.subTest(key=key):
                git(self.p.root, "config", key, value)
                self.assertEqual(self.runner.risky_local_key(), key)
                git(self.p.root, "config", "--unset", key)
        self.assertIsNone(self.runner.risky_local_key())

    def ext_rewrite(self, marker):
        """Config a session could set so that talking to origin runs `touch marker` through the ext transport."""
        git(self.p.root, "config", "protocol.allow", "always")
        git(self.p.root, "config", f"url.ext::sh -c touch% {marker}% #.insteadOf", str(self.origin))

    def test_git_safe_disables_the_ext_transport_even_when_config_enables_it(self):
        marker = self.tmp / "ext-ran"
        self.ext_rewrite(marker)
        self.runner.git("ls-remote", "--heads", "origin")
        self.runner.git("push", "-q", "origin", "HEAD:refs/heads/factory-state")
        self.assertFalse(marker.exists())

    def test_save_refuses_when_factory_jobs_is_a_symlink(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "config").write_text("not job state")
        (self.p.root / "factory/jobs").symlink_to(elsewhere)
        self.assertFalse(self.call(self.runner.save_state))
        self.assertEqual(git(self.tmp, "--git-dir", str(self.origin), "branch", "--list", "factory-state"), "")


FAKE_GH = f"#!{sys.executable}\nimport sys\nsys.stdout.write('[]')\n"


class TickCiTest(CiCase):
    def tick(self, **env):
        fakebin = self.tmp / "cibin"
        fakebin.mkdir(exist_ok=True)
        (fakebin / "gh").write_text(FAKE_GH)
        (fakebin / "gh").chmod(0o755)
        full = {**self.p.env(), "PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}", **env}
        return subprocess.run([sys.executable, str(self.p.root / "factory/bin/runner"), "tick", "--ci"],
                              cwd=self.p.root, capture_output=True, text=True, env=full)

    def test_idle_ci_tick_saves_state_with_its_log(self):
        res = self.tick(CLAUDE_CODE_OAUTH_TOKEN="tok")
        self.assertEqual(res.returncode, 0, res.stderr)
        files = git(self.tmp, "--git-dir", str(self.origin), "ls-tree", "-r", "--name-only", "factory-state").split()
        self.assertIn("runner.log", files)
        self.assertFalse((self.p.git_dir / "factory-runner.lock").exists())

    def test_state_is_restored_before_the_tick(self):
        self.tick(CLAUDE_CODE_OAUTH_TOKEN="tok")
        import shutil
        shutil.rmtree(self.p.root / "factory/jobs")
        self.tick(CLAUDE_CODE_OAUTH_TOKEN="tok")
        lines = (self.p.root / "factory/jobs/runner.log").read_text().splitlines()
        self.assertEqual(len(lines), 2)  # the first tick's line came back from factory-state

    def test_token_comes_from_the_environment_and_leaves_it(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}):
            self.assertEqual(self.runner.ci_token(), "tok")
            self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", os.environ)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
            self.assertIsNone(self.runner.ci_token())

    def test_missing_token_with_work_logs_the_secret_to_add(self):
        base, runner = self.runner.load_config()
        with mock.patch.object(self.runner, "chores"), mock.patch.object(self.runner, "has_work", return_value=True), \
                mock.patch.object(self.runner, "run_orchestrate") as run_orchestrate:
            self.assertEqual(self.runner.tick_body(base, runner, ""), 1)
        run_orchestrate.assert_not_called()
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN isn't set; add the FACTORY_CLAUDE_TOKEN secret",
                      (self.p.root / "factory/jobs/runner.log").read_text())

    def test_plain_tick_on_github_actions_still_reads_the_platform_token(self):
        base, runner = self.runner.load_config()
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), mock.patch.object(self.runner, "chores"), \
                mock.patch.object(self.runner, "has_work", return_value=True), \
                mock.patch.object(self.runner, "read_token", return_value="tok") as read_token, \
                mock.patch.object(self.runner, "missing_sandbox_tools", return_value=[]), \
                mock.patch.object(self.runner.shutil, "which", return_value="/bin/claude"), \
                mock.patch.object(self.runner, "run_orchestrate", return_value=(0, 1)) as run_orchestrate:
            self.assertEqual(self.runner.tick_body(base, runner, None), 0)
        read_token.assert_called_once()
        self.assertEqual(run_orchestrate.call_args.args[0], "tok")


class DoctorCiTest(CiCase):
    def setUp(self):
        super().setUp()
        self.doctor = load_script(f"doctor_ci_{id(self)}", self.p.root / "factory/bin/doctor")
        self.doctor.CI = True
        self.answers = {}
        self.doctor.gh_api = lambda gh, path: self.answers.get(path.rsplit("/", 1)[-1])

    def test_unprotected_state_branch_and_workflow_present_pass(self):
        self.p.write(".github/workflows/factory-runner.yml", "name: factory-runner\n")
        self.assertEqual(self.doctor.ci_state_checks(), [])

    def test_protection_and_blocking_rules_fail(self):
        self.answers = {"protection": {"url": "x"}, "factory-state": [{"type": "non_fast_forward"}]}
        problems = self.doctor.ci_state_checks()
        self.assertIn(("FAIL", "factory-state is protected; the Actions runner must be able to push it"), problems)
        self.assertIn(("FAIL", "rules on factory-state block the runner (non_fast_forward)"), problems)
        self.assertIn(("WARN", "no Actions workflow; /factory-install writes it"), problems)

    def test_check_runner_swaps_token_and_scheduler_checks_for_state_checks(self):
        with mock.patch.object(self.doctor, "platform_name", return_value="Linux"), \
                mock.patch.dict(os.environ, {"PATH": str(self.tmp / "nothing")}):
            messages = [message for _, message in self.doctor.check_runner()]
        self.assertIn("no Actions workflow; /factory-install writes it", messages)
        self.assertFalse([m for m in messages if "token" in m or "timer" in m or "linger" in m or "bwrap" in m], messages)
