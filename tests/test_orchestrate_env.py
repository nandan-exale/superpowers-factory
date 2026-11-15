import os
import signal
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from script_loader import load_script

PLUGIN = Path(__file__).resolve().parents[1]
ORCHESTRATE = PLUGIN / "vendor" / "factory" / "factory" / "bin" / "orchestrate"
CONFIG = {"base_branch": "main", "runtime": "codex",
          "runtimes": {"claude": {"credential_env": "CLAUDE_CODE_OAUTH_TOKEN"},
                       "codex": {"credential_env": "OPENAI_API_KEY"},
                       "opencode": {"credential_env": "ANTHROPIC_PROVIDER_KEY"}}}


class OrchestrateEnvTest(unittest.TestCase):
    def setUp(self):
        self.orch = load_script(ORCHESTRATE, "orchestrate_env_under_test")
        self.seen = {}
        seen = self.seen

        class RecordingLoop:
            def __init__(self, cli, pipeline, runtime, say=print, agent_env=None):
                seen["agent_env"] = dict(agent_env or {})

            def run(self, issue):
                seen["environ"] = dict(os.environ)
                return 0

            def stop(self):
                pass

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cli = types.SimpleNamespace(repo=PLUGIN, config=lambda: CONFIG)
        runtime = types.SimpleNamespace(NAME="codex", BINARY="true", CAPS={"stop_hook": False})
        for target, name, value in ((self.orch, "lock_path", lambda: Path(tmp.name) / "factory-orchestrate.lock"),
                                    (self.orch, "Loop", RecordingLoop), (self.orch, "JobCli", lambda repo: cli),
                                    (self.orch.runtimes, "load", lambda name: runtime)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(signal.signal, signal.SIGTERM, signal.getsignal(signal.SIGTERM))
        environ = mock.patch.dict(os.environ)  # restores whatever the host had, after these pops
        environ.start()
        self.addCleanup(environ.stop)
        for name in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                     "OPENAI_API_KEY", "CODEX_API_KEY", "CURSOR_API_KEY"):
            os.environ.pop(name, None)

    def test_agents_get_only_the_runtime_s_own_credential(self):
        env = {"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "leak", "ANTHROPIC_PROVIDER_KEY": "leak"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(self.orch.main(["run"]), 0)
            left = dict(os.environ)
        self.assertEqual(self.seen["agent_env"], {"OPENAI_API_KEY": "sk-test"})
        for name in env:
            self.assertNotIn(name, left)
            self.assertNotIn(name, self.seen["environ"])

    def test_claude_agents_also_get_the_anthropic_variables(self):
        claude = {**CONFIG, "runtime": "claude"}
        cli = types.SimpleNamespace(repo=PLUGIN, config=lambda: claude)
        env = {"CLAUDE_CODE_OAUTH_TOKEN": "tok", "ANTHROPIC_BASE_URL": "http://x", "OPENAI_API_KEY": "leak"}
        with mock.patch.object(self.orch, "JobCli", lambda repo: cli), mock.patch.dict(os.environ, env):
            self.assertEqual(self.orch.main(["run"]), 0)
        self.assertEqual(self.seen["agent_env"], {"CLAUDE_CODE_OAUTH_TOKEN": "tok", "ANTHROPIC_BASE_URL": "http://x"})


if __name__ == "__main__":
    unittest.main()
