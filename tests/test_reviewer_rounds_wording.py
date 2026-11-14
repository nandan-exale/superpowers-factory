"""Reviewers raise everything blocking in one round.

In jobs 004 and 008 reviewers handed out findings one round at a time (a new route to the same
sandbox escape each round, a phone-width problem their own fix caused), and the UI reviewer blocked
on overflow that was already on main. Each extra round costs a rebuild, a gate and a review.
"""

import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[1] / "vendor/factory/factory/agents"
REVIEWERS = ("reviewer-code", "reviewer-security", "reviewer-ui", "reviewer-ux")


def text(name):
    return " ".join((AGENTS / f"{name}.md").read_text().split())


class ReviewerRoundsWordingTest(unittest.TestCase):
    def test_every_reviewer_raises_blocking_findings_now(self):
        for name in REVIEWERS:
            self.assertIn("Raise every blocking finding in this round", text(name), name)

    def test_security_looks_for_every_route_and_a_fix_for_the_kind(self):
        t = text("reviewer-security")
        self.assertIn("look for every other route of the same kind", t)
        self.assertIn("a fix that closes the whole kind", t)

    def test_security_checks_fixes_close_the_kind(self):
        self.assertIn("closes the problem, not only the example you gave", text("reviewer-security"))

    def test_ui_does_not_block_on_what_the_base_already_has(self):
        self.assertIn("Don't block on problems the base branch already has", text("reviewer-ui"))

    def test_ui_checks_both_widths_every_round(self):
        self.assertIn("In every round, check desktop and phone widths", text("reviewer-ui"))
        self.assertIn("holds at both widths", text("reviewer-ui"))


if __name__ == "__main__":
    unittest.main()
