import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import FactoryProject  # noqa: E402


class TierCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.project.set_issue("Build it.", labels=("factory",))

    def configure(self, **changes):
        path = self.project.repo / "factory" / "config.json"
        cfg = json.loads(path.read_text())
        for dotted, value in changes.items():
            node, *keys = [cfg, *dotted.split("__")]
            for key in keys[:-1]:
                node = node[key]
            node[keys[-1]] = value
        path.write_text(json.dumps(cfg))
        self.job = self.project.load_job()
        # job loads the runtime's adapter for its CAPS; codex and cursor's adapters arrive in Tasks 8–11.
        self.job.runtime_caps = lambda: {"reports_cost": True, "reports_tokens": True}
        self.job_id = self.project.create_job(self.job)

    def agent(self, role):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.main(["agent", self.job_id, role])
        return out.getvalue().splitlines()


class TierTest(TierCase):
    def test_claude_resolves_tier_to_alias(self):
        self.configure()
        self.assertEqual(self.agent("intake"), ["model=fable effort=high"])

    def test_other_runtime_uses_its_tiers_and_nearest_lower_effort(self):
        self.configure(runtime="codex",
                       runtimes__codex__tiers={"fast": "m-mini", "balanced": "m", "strong": "m-max", "frontier": "m-max"},
                       agents__intake={"tier": "frontier", "effort": "max"})
        self.assertEqual(self.agent("intake"),
                         ["model=m-max effort=high", "NOTE: effort max → high (codex supports low, medium, high)"])

    def test_runtime_without_efforts_prints_none(self):
        self.configure(runtime="cursor", runtimes__cursor__tiers={"fast": "a", "balanced": "a", "strong": "a",
                                                                   "frontier": "a"})
        self.assertEqual(self.agent("intake"), ["model=a effort=none"])

    def test_missing_tier_refuses_and_names_the_key(self):
        self.configure(runtime="copilot")
        with self.assertRaises(SystemExit):
            self.agent("intake")

    def test_legacy_model_entry_in_an_old_job_still_resolves(self):
        self.configure()
        self.assertEqual(self.job.resolve_setting("routing.x", {"model": "opus", "effort": "high"}),
                         ("opus", "high", None))

    def test_unknown_runtime_refuses(self):
        self.configure(runtime="nope")
        with self.assertRaises(SystemExit):
            self.agent("intake")


if __name__ == "__main__":
    unittest.main()
