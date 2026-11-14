"""The builder checks its own diff for what reviewers kept sending back.

Jobs 006, 007, 009 and 013 each lost a round to a code-review finding the builder could have seen:
an error case from the spec with no test, an unguarded external program, a failure left to raise,
and constants the change left unused.
"""

import unittest
from pathlib import Path

BUILDER = Path(__file__).resolve().parents[1] / "vendor/factory/factory/agents/builder.md"


class BuilderSelfCheckWordingTest(unittest.TestCase):
    def setUp(self):
        self.text = " ".join(BUILDER.read_text().split())

    def test_has_a_self_check_before_ready(self):
        self.assertIn("## Before STATUS: READY", BUILDER.read_text())
        self.assertIn("Read your own diff (`git diff <base>...HEAD`) once", self.text)

    def test_each_error_case_in_the_spec_has_a_test(self):
        self.assertIn("Every error case the spec names has a test that exercises it", self.text)

    def test_failures_are_handled_not_left_to_raise(self):
        self.assertIn("handled the way the spec says, not left to raise", self.text)

    def test_external_programs_are_guarded_like_their_neighbours(self):
        self.assertIn("missing the way the neighbouring code does", self.text)

    def test_nothing_is_left_unused(self):
        self.assertIn("Nothing your change made unused is left behind", self.text)


if __name__ == "__main__":
    unittest.main()
