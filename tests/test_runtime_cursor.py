import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_contract import RuntimeContract  # noqa: E402


class CursorContractTest(RuntimeContract, unittest.TestCase):
    NAME = "cursor"

    def test_args(self):
        argv, _ = self.rt.build(self.run_for(resume="c-1"))
        self.assertEqual(argv[:4], ["cursor-agent", "-p", "--output-format", "json"])
        self.assertIn("--force", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], "c-1")
        self.assertIn("TASK PROMPT", argv[-1])


if __name__ == "__main__":
    unittest.main()
