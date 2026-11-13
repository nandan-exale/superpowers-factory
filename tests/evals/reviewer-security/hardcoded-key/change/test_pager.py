import unittest

from pager import page


class PageTest(unittest.TestCase):
    def test_first_page(self):
        self.assertEqual(page([1, 2, 3, 4, 5], 1, 2), [1, 2])

    def test_last_partial_page(self):
        self.assertEqual(page([1, 2, 3, 4, 5], 3, 2), [5])

    def test_page_count_exact(self):
        from pager import page_count
        self.assertEqual(page_count([1, 2, 3, 4], 2), 2)

    def test_page_count_partial(self):
        from pager import page_count
        self.assertEqual(page_count([1, 2, 3, 4, 5], 2), 3)


if __name__ == "__main__":
    unittest.main()
