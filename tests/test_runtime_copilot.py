import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_contract import RuntimeContract  # noqa: E402

DENIED_FORCE = "shell(git push " + "--force)"

SAMPLE = (
    '{"type":"session.start","data":{"sessionId":"8cc6f8a9-e53a-45d1-93d6-eee21a0d7cd6"}}\n'
    '{"type":"session.warning","data":{"warningType":"policy","message":"x"}}\n'
    '{"type":"result","data":{}}\n'
)


class CopilotContractTest(RuntimeContract, unittest.TestCase):
    NAME = "copilot"

    def test_args(self):
        argv, _ = self.rt.build(self.run_for(resume="8cc6"))
        self.assertEqual(argv[0], "copilot")
        self.assertIn("--allow-all-tools", argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(argv[argv.index("--resume") + 1], "8cc6")
        self.assertIn("TASK PROMPT", argv[argv.index("-p") + 1])
        self.assertIn(DENIED_FORCE, argv)


class CopilotShapeTest(unittest.TestCase):
    def setUp(self):
        import runtimes
        self.rt = runtimes.load("copilot")

    def test_session_from_session_start(self):
        r = self.rt.parse(SAMPLE)
        self.assertEqual(r["session_id"], "8cc6f8a9-e53a-45d1-93d6-eee21a0d7cd6")
        self.assertFalse(r["error"])

    def test_no_result_event_is_an_error(self):
        self.assertTrue(self.rt.parse(SAMPLE.rsplit("\n", 2)[0] + "\n")["error"])

    def test_error_event_is_an_error(self):
        self.assertTrue(self.rt.parse(SAMPLE + '{"type":"session.error","data":{"message":"boom"}}\n')["error"])


if __name__ == "__main__":
    unittest.main()
