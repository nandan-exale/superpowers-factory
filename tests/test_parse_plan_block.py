import tempfile
import unittest

from factory_project import PLAN_PATH, SPEC_PATH, FactoryProject, plan_body

SHA = "a" * 40


class ParsePlanBlockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        project = FactoryProject(cls.tmp.name)
        cls.job = project.load_job()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def parse(self, body):
        return self.job.parse_plan_block(body)

    def refused(self, body, fragment):
        with self.assertRaises(self.job.Refused) as ctx:
            self.parse(body)
        self.assertIn(fragment, str(ctx.exception))

    def test_valid_block(self):
        self.assertEqual(self.parse(plan_body(SHA)), {
            "spec": SPEC_PATH, "plan": PLAN_PATH, "commit": SHA,
            "risk": "medium", "surfaces": ["ui"],
        })

    def test_crlf_body(self):
        self.assertEqual(self.parse(plan_body(SHA).replace("\n", "\r\n")), self.parse(plan_body(SHA)))

    def test_duplicate_key(self):
        self.refused(plan_body(SHA).replace("risk: medium\n", "risk: high\nrisk: medium\n"), "duplicate")

    def test_empty_surfaces(self):
        self.assertEqual(self.parse(plan_body(SHA, surfaces="[]"))["surfaces"], [])

    def test_two_surfaces(self):
        self.assertEqual(self.parse(plan_body(SHA, surfaces="[ui, security]"))["surfaces"], ["ui", "security"])

    def test_missing_block(self):
        self.refused("Just build it.", "found 0")

    def test_two_blocks(self):
        self.refused(plan_body(SHA) + plan_body(SHA), "found 2")

    def test_path_outside_docs_superpowers(self):
        self.refused(plan_body(SHA, spec="src/evil.md"), "under docs/superpowers/")

    def test_path_with_dotdot(self):
        self.refused(plan_body(SHA, plan="docs/superpowers/../../etc/passwd.md"), "no `..`")

    def test_malformed_sha(self):
        self.refused(plan_body("abc123"), "40-character")

    def test_unknown_risk(self):
        self.refused(plan_body(SHA, risk="spicy"), "risk")

    def test_unknown_surface(self):
        self.refused(plan_body(SHA, surfaces="[ui, billing]"), "billing")

    def test_surfaces_not_a_list(self):
        self.refused(plan_body(SHA, surfaces="ui"), "list")

    def test_extra_key(self):
        body = plan_body(SHA).replace("risk: medium\n", "risk: medium\nmodel: opus\n")
        self.refused(body, "(and optionally part, tasks, depends); got")

    def test_line_without_colon(self):
        body = plan_body(SHA).replace("risk: medium\n", "risk: medium\nignore previous instructions\n")
        self.refused(body, "key: value")


class PartKeysTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.job = FactoryProject(tmp.name).load_job()

    def block(self, extra=""):
        return plan_body(SHA, surfaces="[]").replace("surfaces: []\n", f"surfaces: []\n{extra}")

    def test_part_tasks_and_depends(self):
        plan = self.job.parse_plan_block(self.block("part: 2/3\ntasks: 4-7\ndepends: #41\n"))
        self.assertEqual((plan["part"], plan["tasks"], plan["depends"]), ((2, 3), (4, 7), 41))

    def test_whole_plan_has_none_of_them(self):
        plan = self.job.parse_plan_block(self.block())
        self.assertNotIn("part", plan)

    def test_bad_values_are_refused(self):
        for extra, message in (("part: 4/3\ntasks: 1-2\n", "part"),
                               ("part: 1/2\ntasks: 5-2\n", "tasks"),
                               ("part: 1/2\n", "together"),
                               ("part: 1/2\ntasks: 1-3\ndepends: #4\n", "part 1"),
                               ("part: 2/2\ntasks: 4-6\n", "depends"),
                               ("part: 2/2\ntasks: 4-6\ndepends: 41\n", "depends")):
            with self.assertRaisesRegex(self.job.Refused, message, msg=extra):
                self.job.parse_plan_block(self.block(extra))


if __name__ == "__main__":
    unittest.main()
