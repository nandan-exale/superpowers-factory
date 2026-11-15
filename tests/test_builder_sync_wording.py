import unittest
from pathlib import Path

BUILDER = Path(__file__).resolve().parents[1] / "vendor/factory/factory/agents/builder.md"


class BuilderSyncWordingTest(unittest.TestCase):
    """The builder's sandbox can't write protected files, so its own merge of the base fails whenever the
    base changed one (job 016). The factory syncs the branch before each round instead."""

    def setUp(self):
        self.text = " ".join(BUILDER.read_text().split())

    def test_builder_never_merges_the_base_itself(self):
        self.assertIn("Never merge or rebase the base branch yourself", self.text)

    def test_the_factory_syncs_before_each_later_round(self):
        self.assertIn("the factory merges the base into the branch before each round after the first", self.text)

    def test_feedback_asking_for_a_merge_means_the_factorys_merge(self):
        self.assertIn("When feedback asks you to merge the base, that is the merge your prompt names", self.text)


if __name__ == "__main__":
    unittest.main()
