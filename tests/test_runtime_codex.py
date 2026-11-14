import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_contract import RuntimeContract  # noqa: E402


class CodexContractTest(RuntimeContract, unittest.TestCase):
    NAME = "codex"

    def test_write_access_args(self):
        argv, _ = self.rt.build(self.run_for())
        self.assertEqual(argv[:2], ["codex", "exec"])
        self.assertIn("--json", argv)
        self.assertIn('sandbox_mode="workspace-write"', argv)
        roots = next(a for a in argv if a.startswith("sandbox_workspace_write.writable_roots="))
        self.assertIn(json.dumps(str(self.repo / ".git")), roots)
        self.assertIn('model_reasoning_effort="high"', argv)
        self.assertNotIn("--sandbox", argv)   # `codex exec resume` has no --sandbox or --add-dir
        self.assertNotIn("--add-dir", argv)
        self.assertEqual(argv[-1], "-")

    def test_resume_uses_the_resume_subcommand_with_the_same_sandbox(self):
        argv, _ = self.rt.build(self.run_for(resume="t-1"))
        self.assertEqual(argv[:4], ["codex", "exec", "resume", "t-1"])
        self.assertIn('sandbox_mode="workspace-write"', argv)

    def test_cached_tokens_are_not_counted_twice(self):
        out = ('{"type":"thread.started","thread_id":"t"}\n'
               '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":60,"output_tokens":5}}\n')
        u = self.rt.parse(out)["usage"]
        self.assertEqual((u["input_tokens"], u["cache_read_input_tokens"], u["output_tokens"]), (40, 60, 5))

    def test_effort_none_passes_no_effort(self):
        run = {**self.run_for(), "effort": "none"}
        self.assertFalse(any("model_reasoning_effort" in a for a in self.rt.build(run)[0]))

    def test_turn_failed_is_an_error(self):
        out = '{"type":"thread.started","thread_id":"t"}\n{"type":"turn.failed","error":{"message":"x"}}\n'
        self.assertTrue(self.rt.parse(out)["error"])


if __name__ == "__main__":
    unittest.main()
