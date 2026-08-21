import unittest
from unittest.mock import patch

import app.main


class MainEntrypointTest(unittest.TestCase):
    @patch("app.main.main")
    def test_module_exposes_langgraph_cli(self, mocked_main):
        self.assertTrue(callable(app.main.main))
        mocked_main.assert_not_called()


if __name__ == "__main__":
    unittest.main()
