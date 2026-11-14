import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from factory_project import FactoryProject

INTAKE = "DECISION: {decision}\nRISK: {risk}\nSURFACES: {surfaces}\nRESCOPED: no\n\n## Summary\n- test\n"
LOW = {
    "spec-writer": {"tier": "strong", "effort": "medium"},
    "builder": {"tier": "balanced", "effort": "medium"},
    "approver": {"tier": "strong", "effort": "medium"},
    "reviewers": {"code": {"tier": "fast", "effort": "medium"}},
}


class RoutingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = FactoryProject(self.tmp.name)
        self.project.set_issue("Build the widget.", labels=("factory",))
        self.job = self.project.load_job()
        self.job_id = self.project.create_job(self.job)
        self.d = self.job.job_dir(self.job_id)

    def tearDown(self):
        self.tmp.cleanup()

    def accept(self, risk="low", surfaces="none", decision="ACCEPT"):
        (self.d / "intake.md").write_text(INTAKE.format(decision=decision, risk=risk, surfaces=surfaces))

    def edit_config(self, change):
        """Change the project's config.json and re-import bin/job. Call before any load()."""
        path = self.project.repo / "factory" / "config.json"
        config = json.loads(path.read_text())
        change(config)
        path.write_text(json.dumps(config))
        self.job = self.project.load_job()

    def current(self):
        return self.job.sync(self.job.load(self.job_id))

    def route(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_route(self.current())
        return out.getvalue()

    def agent(self, role):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_agent(self.current(), role)
        return out.getvalue().strip()

    def refused(self, fragment):
        with self.assertRaises(self.job.Refused) as ctx:
            self.route()
        self.assertIn(fragment, str(ctx.exception))


class RouteTest(RoutingTestCase):
    def test_low_risk_no_surfaces(self):
        self.accept("low")
        self.route()
        self.assertEqual(self.job.load(self.job_id)["agents"], LOW)

    def test_high_risk_with_surfaces(self):
        self.accept("high", "ui, security")
        self.route()
        agents = self.job.load(self.job_id)["agents"]
        self.assertEqual(agents["builder"], {"tier": "strong", "effort": "high"})
        self.assertEqual(agents["reviewers"], {
            "code": {"tier": "balanced", "effort": "high"},
            "ux": {"tier": "balanced", "effort": "medium"},
            "ui": {"tier": "fast", "effort": "medium"},
            "security": {"tier": "strong", "effort": "high"},
        })

    def test_medium_risk_builder_is_balanced(self):
        # Builders were 71% of the factory's tokens; Opus builds only high-risk jobs by default.
        self.accept("medium")
        self.route()
        self.assertEqual(self.job.load(self.job_id)["agents"]["builder"], {"tier": "balanced", "effort": "high"})

    def test_route_prints_every_agent(self):
        self.accept("low")
        out = self.route()
        self.assertIn("builder balanced/medium", out)
        self.assertIn("code fast/medium", out)

    def test_route_refuses_job_intake_did_not_accept(self):
        self.accept("low", decision="REJECT")
        with self.assertRaises(SystemExit):
            self.route()


class RouteValidationTest(RoutingTestCase):
    def test_unknown_tier(self):
        self.edit_config(lambda c: c["routing"]["low"]["builder"].update(tier="huge"))
        self.accept("low")
        self.refused("routing.low.builder.tier 'huge' isn't one of fast, balanced, strong, frontier")

    def test_unknown_legacy_model(self):
        self.edit_config(lambda c: c["routing"]["low"].update(builder={"model": "gpt", "effort": "high"}))
        self.accept("low")
        self.refused("routing.low.builder.model 'gpt' isn't a known alias; use tier")

    def test_unknown_effort(self):
        self.edit_config(lambda c: c["routing"]["low"]["builder"].update(effort="ludicrous"))
        self.accept("low")
        self.refused("routing.low.builder.effort 'ludicrous' isn't one of low, medium, high, xhigh, max")

    def test_missing_role(self):
        self.edit_config(lambda c: c["routing"]["low"].pop("approver"))
        self.accept("low")
        self.refused("routing.low is missing: approver")

    def test_old_string_setting(self):
        self.edit_config(lambda c: c["routing"]["low"].update(code="haiku"))
        self.accept("low")
        self.refused("routing.low.code must be {tier, effort}")

    def test_bad_surface_setting(self):
        self.edit_config(lambda c: c["surface_reviewers"]["ui"]["ux"].update(tier="gpt"))
        self.accept("low", "ui")
        self.refused("surface_reviewers.ui.ux.tier 'gpt'")

    def test_unknown_surface(self):
        self.accept("low", "billing")
        self.refused("surface 'billing' isn't in config.json surface_reviewers")

    def test_unknown_risk(self):
        self.accept("spicy")
        self.refused("risk 'spicy' isn't in config.json routing")


class AgentTest(RoutingTestCase):
    def test_intake_from_config(self):
        self.assertEqual(self.agent("intake"), "model=opus effort=high")

    def test_routed_agent_and_reviewer(self):
        self.accept("medium", "ui")
        self.route()
        self.assertEqual(self.agent("builder"), "model=sonnet effort=high")
        self.assertEqual(self.agent("reviewer-ux"), "model=sonnet effort=medium")

    def test_role_before_routing_exits(self):
        with self.assertRaises(SystemExit):
            self.agent("builder")

    def test_reviewer_not_routed_exits(self):
        self.accept("low")
        self.route()
        with self.assertRaises(SystemExit):
            self.agent("reviewer-ux")

    def test_bad_intake_config_refused(self):
        self.edit_config(lambda c: c["agents"]["intake"].update(tier="gpt"))
        with self.assertRaises(self.job.Refused) as ctx:
            self.agent("intake")
        self.assertIn("agents.intake.tier 'gpt'", str(ctx.exception))

    def test_job_routed_before_tiers_still_resolves(self):
        job = self.job.load(self.job_id)
        self.job.save({**job, "agents": {**LOW, "builder": {"model": "sonnet", "effort": "low"}}})
        self.assertEqual(self.agent("builder"), "model=sonnet effort=low")

    def test_missing_tier_exits_naming_the_key(self):
        self.edit_config(lambda c: c["runtimes"]["claude"]["tiers"].pop("strong"))
        res = subprocess.run([str(self.project.repo / "factory" / "bin" / "job"), "agent", self.job_id, "intake"],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("runtimes.claude.tiers.strong isn't set", res.stderr)


class RouteWrapperTest(RoutingTestCase):
    def test_bin_route_runs_job_route(self):
        self.accept("low")
        res = subprocess.run([str(self.project.repo / "factory" / "bin" / "route"), self.job_id],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("code fast/medium", res.stdout)
        self.assertEqual(json.loads((self.d / "job.json").read_text())["agents"], LOW)


class DefaultAgentsTest(unittest.TestCase):
    def test_intake_runs_on_the_strong_tier(self):
        cfg = json.loads((Path(__file__).resolve().parents[1] / "vendor/factory/factory/config.json").read_text())
        self.assertEqual(cfg["agents"]["intake"], {"tier": "strong", "effort": "high"})


if __name__ == "__main__":
    unittest.main()
