import unittest
from unittest.mock import patch

from app.graph import nodes
from app.graph.cli import collect_dft_execution_options
from app.graph.routes import route_after_dft_execution_options


class DFTExecutionOptionsTest(unittest.TestCase):
    def test_bulk_jobs_are_exposed(self):
        with patch(
            "app.graph.nodes.interrupt",
            return_value={"mode": "relax_only"},
        ):
            result = nodes.dft_execution_options_node({
                "bulk_dft_jobs": [{
                    "job_id": "B1",
                    "structure_id": "S1",
                    "job_dir": "bulk-job",
                }],
                "dft_jobs": [],
            })

        self.assertEqual(
            result["dft_job_source"],
            "c6d_bulk_formation",
        )
        self.assertEqual(
            result["dft_execution_options"]["energy_source"],
            "relax",
        )

    def test_static_mode_is_recorded(self):
        with patch(
            "app.graph.nodes.interrupt",
            return_value={"mode": "relax_then_static"},
        ):
            result = nodes.dft_execution_options_node({
                "bulk_dft_jobs": [{"job_id": "B1"}],
            })

        self.assertEqual(
            result["dft_execution_options"]["energy_source"],
            "static",
        )

    def test_defer_routes_to_end(self):
        route = route_after_dft_execution_options({
            "dft_execution_options": {
                "action": "defer",
            }
        })
        self.assertEqual(route, "end")

    @patch("builtins.input", side_effect=["bad", "2"])
    def test_cli_retries_invalid_input(self, mocked_input):
        result = collect_dft_execution_options({})
        self.assertEqual(
            result["mode"],
            "relax_then_static",
        )


if __name__ == "__main__":
    unittest.main()