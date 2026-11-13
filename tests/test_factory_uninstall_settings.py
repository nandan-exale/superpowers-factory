import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "bin/factory-uninstall-settings"
FACTORY_HOOK = {"type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/factory/bin/stop-hook", "timeout": 600}
OTHER_HOOK = {"type": "command", "command": "scripts/lint"}


class UninstallSettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / ".claude").mkdir()
        self.path = self.root / ".claude/settings.json"

    def run_tool(self):
        return subprocess.run([sys.executable, str(TOOL), str(self.root)], capture_output=True, text=True)

    def write(self, data, indent=2):
        self.path.write_text(json.dumps(data, indent=indent) + "\n")

    def read(self):
        return json.loads(self.path.read_text())

    def test_only_the_factory_hook_is_removed(self):
        self.write({"model": "x", "hooks": {"Stop": [{"hooks": [FACTORY_HOOK, OTHER_HOOK]}],
                                            "PreToolUse": [{"hooks": [OTHER_HOOK]}]}})
        res = self.run_tool()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.read(), {"model": "x", "hooks": {"Stop": [{"hooks": [OTHER_HOOK]}],
                                                               "PreToolUse": [{"hooks": [OTHER_HOOK]}]}})

    def test_empty_containers_are_dropped(self):
        self.write({"model": "x", "hooks": {"Stop": [{"hooks": [FACTORY_HOOK]}]}})
        self.run_tool()
        self.assertEqual(self.read(), {"model": "x"})

    def test_key_order_and_indent_are_kept(self):
        self.write({"a": 1, "hooks": {"Stop": [{"hooks": [FACTORY_HOOK]}], "X": []}, "z": 2}, indent=4)
        self.run_tool()
        text = self.path.read_text()
        self.assertEqual(list(json.loads(text)), ["a", "hooks", "z"])
        self.assertIn('\n    "a": 1', text)

    def test_invalid_json_is_refused_and_untouched(self):
        self.path.write_text("{not json")
        res = self.run_tool()
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.path.read_text(), "{not json")

    def test_nothing_to_do(self):
        self.write({"hooks": {"Stop": [{"hooks": [OTHER_HOOK]}]}})
        before = self.path.read_text()
        res = self.run_tool()
        self.assertEqual(res.returncode, 0)
        self.assertEqual(self.path.read_text(), before)

    def test_missing_file_is_fine(self):
        self.assertEqual(self.run_tool().returncode, 0)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
