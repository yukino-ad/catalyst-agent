import unittest

from scripts.run_tests import classified_modules, discover_module_names


class TestSuiteClassificationTest(unittest.TestCase):
    def test_every_module_is_classified_exactly_once(self):
        discovered = discover_module_names()
        groups = classified_modules()
        fast = groups["fast"]
        integration = groups["integration"]
        e2e = groups["e2e"]
        self.assertFalse(fast & integration)
        self.assertFalse(fast & e2e)
        self.assertFalse(integration & e2e)
        self.assertEqual(fast | integration | e2e, discovered)

    def test_all_suite_matches_discovery(self):
        self.assertEqual(
            classified_modules()["all"],
            discover_module_names(),
        )


if __name__ == "__main__":
    unittest.main()
