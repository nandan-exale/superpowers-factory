import unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1] / "vendor/factory/factory/dashboard.html"


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.html = DASHBOARD.read_text()

    def test_summary_strip_reads_report_json_and_hides_without_it(self):
        self.assertIn('id="strip"', self.html)
        self.assertIn("jobs/report.json", self.html)
        self.assertIn("$('strip').hidden = true", self.html)

    def test_strip_says_day_for_a_one_day_report(self):
        self.assertIn("day${r.days === 1 ? '' : 's'}", self.html)

    def test_strip_lines_up_with_the_board_and_uses_the_line_token(self):
        rule = self.html[self.html.index("  .strip {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("padding: 6px 32px", rule)
        self.assertIn("var(--line)", rule)

    def test_strip_and_pause_use_the_phone_gutter(self):
        phone = self.html[self.html.index("@media (max-width: 640px)"):]
        phone = phone[:phone.index("\n  }\n")]
        self.assertIn(".strip { padding: 6px 16px; }", phone)
        self.assertIn(".pause { margin-left: 0; }", phone)

    def test_pause_toggle(self):
        self.assertIn('id="pause"', self.html)
        self.assertIn("if (paused) return", self.html)

    def test_folders_without_job_json_are_skipped(self):
        self.assertIn(".filter(Boolean)", self.html)
