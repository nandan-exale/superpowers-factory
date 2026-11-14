import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_contract import RuntimeContract  # noqa: E402


class OpencodeContractTest(RuntimeContract, unittest.TestCase):
    NAME = "opencode"

    def test_args_and_permissions(self):
        argv, env = self.rt.build(self.run_for())
        self.assertEqual(argv[:4], ["opencode", "run", "--format", "json"])
        self.assertEqual(argv[argv.index("-m") + 1], "m1")
        config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        self.assertEqual(config["permission"]["webfetch"], "deny")
        self.assertIn("TASK PROMPT", argv[-1])

    def test_resume_passes_the_session(self):
        argv, _ = self.rt.build(self.run_for(resume="ses_1"))
        self.assertEqual(argv[argv.index("--session") + 1], "ses_1")


if __name__ == "__main__":
    unittest.main()
