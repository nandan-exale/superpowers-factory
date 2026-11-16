import unittest

from pager import page


class PageTest(unittest.TestCase):
    def test_first_page(self):
        self.assertEqual(page([1, 2, 3, 4, 5], 1, 2), [1, 2])

    def test_last_partial_page(self):
        self.assertEqual(page([1, 2, 3, 4, 5], 3, 2), [5])


if __name__ == "__main__":
    unittest.main()
