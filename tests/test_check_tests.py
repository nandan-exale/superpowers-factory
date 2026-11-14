"""scripts/check runs the unit test modules in parallel processes."""

import tempfile
import textwrap
import unittest
from argparse import Namespace
from pathlib import Path

from script_loader import load_script

CHECK = load_script(Path(__file__).resolve().parents[1] / "scripts" / "check", "check_script")

# Each module marks its start, then waits for the other's mark: both pass only if they run at once.
MEETS = textwrap.dedent("""
    import time, unittest
    from pathlib import Path
    HERE = Path(__file__).parent

    class T(unittest.TestCase):
        def test_meet(self):
            (HERE / "{me}.started").touch()
            end = time.time() + 20
            while not (HERE / "{other}.started").exists():
                self.assertLess(time.time(), end, "the other module never started")
                time.sleep(0.05)
""")

PASSES = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
FAILS = ("import unittest\nclass T(unittest.TestCase):\n"
         "    def test_bad(self):\n        self.assertEqual(1, 2, 'one is not two')\n")


class CheckTestsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "tests").mkdir()

    def module(self, name, text):
        (self.root / "tests" / f"{name}.py").write_text(text)

    def check(self):
        return CHECK.check_tests(self.root, Namespace())

    def test_passing_modules_pass(self):
        self.module("test_a", PASSES)
        self.module("test_b", PASSES)
        self.assertEqual(self.check(), [])

    def test_modules_run_at_the_same_time(self):
        self.module("test_a", MEETS.format(me="a", other="b"))
        self.module("test_b", MEETS.format(me="b", other="a"))
        self.assertEqual(self.check(), [])

    def test_a_failure_names_its_module_and_shows_the_failure(self):
        self.module("test_a", PASSES)
        self.module("test_b", FAILS)
        problems = "\n".join(self.check())
        self.assertIn("test_b", problems)
        self.assertIn("one is not two", problems)
        self.assertNotIn("test_a", problems)

    def test_only_top_level_test_modules_run(self):
        self.module("test_a", PASSES)
        self.module("helper", FAILS)
        (self.root / "tests" / "e2e").mkdir()
        (self.root / "tests" / "e2e" / "test_nested.py").write_text(FAILS)
        self.assertEqual(self.check(), [])


if __name__ == "__main__":
    unittest.main()
