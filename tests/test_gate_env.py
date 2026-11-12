import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from installed_project import VENDOR, load_script

SECRETS = {"CLAUDE_CODE_OAUTH_TOKEN": "tok", "ANTHROPIC_API_KEY": "key",
           "ANTHROPIC_AUTH_TOKEN": "auth", "ANTHROPIC_BASE_URL": "http://x"}


class GateEnvTest(unittest.TestCase):
    def test_checks_run_without_claude_credentials(self):
        gate = load_script("gate_under_test", VENDOR / "factory/bin/gate")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "env.txt"
            script = Path(tmp) / "checks.sh"
            script.write_text(f"env > '{out}'\n")
            with mock.patch.object(gate, "CHECKS", script), mock.patch.dict(os.environ, SECRETS):
                code, _, _ = gate.run_checks(tmp)
            seen = out.read_text()
        self.assertEqual(code, 0)
        self.assertIn("PATH=", seen)
        for name in SECRETS:
            self.assertNotIn(name, seen)


if __name__ == "__main__":
    unittest.main()
