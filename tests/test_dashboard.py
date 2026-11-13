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

    def test_pause_toggle(self):
        self.assertIn('id="pause"', self.html)
        self.assertIn("if (paused) return", self.html)

    def test_folders_without_job_json_are_skipped(self):
        self.assertIn(".filter(Boolean)", self.html)
