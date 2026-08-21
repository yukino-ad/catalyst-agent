import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.c117_formation_energy_cli import calculate


class C117CLITest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.link = Path(self.temporary.name) / "link.json"
        self.link.write_text(
            json.dumps({"alloy_slurm_job_id": "123"}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    @patch("app.c117_formation_energy_cli.FormationEnergyBackfillService")
    def test_expected_job_id_is_checked(self, service_class):
        with self.assertRaisesRegex(ValueError, "does not match"):
            calculate(str(self.link), "456")
        service_class.return_value.calculate.assert_not_called()

    @patch("app.c117_formation_energy_cli.FormationEnergyBackfillService")
    def test_matching_job_id_returns_result(self, service_class):
        expected = {"slurm_job_id": "123", "status": "ok"}
        service_class.return_value.calculate.return_value = expected
        self.assertEqual(calculate(str(self.link), "123"), expected)


if __name__ == "__main__":
    unittest.main()
