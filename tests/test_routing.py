import contextlib
import io
import json
import subprocess
import tempfile
import unittest

from factory_project import FactoryProject

INTAKE = "DECISION: {decision}\nRISK: {risk}\nSURFACES: {surfaces}\nRESCOPED: no\n\n## Summary\n- test\n"
LOW = {
    "spec-writer": {"model": "opus", "effort": "medium"},
    "builder": {"model": "opus", "effort": "medium"},
    "approver": {"model": "opus", "effort": "medium"},
    "reviewers": {"code": {"model": "haiku", "effort": "medium"}},
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
        self.assertEqual(agents["builder"], {"model": "opus", "effort": "high"})
        self.assertEqual(agents["reviewers"], {
            "code": {"model": "sonnet", "effort": "high"},
            "ux": {"model": "sonnet", "effort": "medium"},
            "ui": {"model": "haiku", "effort": "medium"},
            "security": {"model": "opus", "effort": "high"},
        })

    def test_route_prints_every_agent(self):
        self.accept("low")
        out = self.route()
        self.assertIn("builder opus/medium", out)
        self.assertIn("code haiku/medium", out)

    def test_route_refuses_job_intake_did_not_accept(self):
        self.accept("low", decision="REJECT")
        with self.assertRaises(SystemExit):
            self.route()


class RouteValidationTest(RoutingTestCase):
    def test_unknown_model(self):
        self.edit_config(lambda c: c["routing"]["low"]["builder"].update(model="gpt"))
        self.accept("low")
        self.refused("routing.low.builder.model 'gpt' isn't in model_aliases")

    def test_unknown_effort(self):
        self.edit_config(lambda c: c["routing"]["low"]["builder"].update(effort="ludicrous"))
        self.accept("low")
        self.refused("routing.low.builder.effort 'ludicrous' isn't in effort_levels")

    def test_missing_role(self):
        self.edit_config(lambda c: c["routing"]["low"].pop("approver"))
        self.accept("low")
        self.refused("routing.low is missing: approver")

    def test_old_string_setting(self):
        self.edit_config(lambda c: c["routing"]["low"].update(code="haiku"))
        self.accept("low")
        self.refused("routing.low.code must be {model, effort}")

    def test_bad_surface_setting(self):
        self.edit_config(lambda c: c["surface_reviewers"]["ui"]["ux"].update(model="gpt"))
        self.accept("low", "ui")
        self.refused("surface_reviewers.ui.ux.model 'gpt'")

    def test_unknown_surface(self):
        self.accept("low", "billing")
        self.refused("surface 'billing' isn't in config.json surface_reviewers")

    def test_unknown_risk(self):
        self.accept("spicy")
        self.refused("risk 'spicy' isn't in config.json routing")


class AgentTest(RoutingTestCase):
    def test_intake_from_config(self):
        self.assertEqual(self.agent("intake"), "model=fable effort=high")

    def test_routed_agent_and_reviewer(self):
        self.accept("medium", "ui")
        self.route()
        self.assertEqual(self.agent("builder"), "model=opus effort=high")
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
        self.edit_config(lambda c: c["agents"]["intake"].update(model="gpt"))
        with self.assertRaises(self.job.Refused) as ctx:
            self.agent("intake")
        self.assertIn("agents.intake.model 'gpt'", str(ctx.exception))


class RouteWrapperTest(RoutingTestCase):
    def test_bin_route_runs_job_route(self):
        self.accept("low")
        res = subprocess.run([str(self.project.repo / "factory" / "bin" / "route"), self.job_id],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("code haiku/medium", res.stdout)
        self.assertEqual(json.loads((self.d / "job.json").read_text())["agents"], LOW)


if __name__ == "__main__":
    unittest.main()
