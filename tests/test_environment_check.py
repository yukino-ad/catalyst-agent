import unittest
from unittest.mock import patch

from app.environment_check import inspect_environment


class EnvironmentCheckTest(unittest.TestCase):
    def test_result_has_reproducibility_checks(self):
        result = inspect_environment()
        self.assertIn("supported_python", result["checks"])
        self.assertIn("inside_project_venv", result["checks"])
        self.assertIn("dependencies_available", result["checks"])
        self.assertIn("cluster_safe_by_default", result["checks"])

    @patch.dict("os.environ", {
        "CLUSTER_REMOTE_WRITE_ENABLED": "false",
        "CLUSTER_SUBMISSION_ENABLED": "false",
    })
    def test_disabled_cluster_writes_are_safe(self):
        result = inspect_environment()
        self.assertTrue(result["checks"]["cluster_safe_by_default"])


if __name__ == "__main__":
    unittest.main()
