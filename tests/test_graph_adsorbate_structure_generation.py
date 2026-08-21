import json
import unittest
from unittest.mock import patch

from app.graph.nodes import (
    adsorbate_structure_generation_node,
)


class GraphAdsorbateStructureGenerationTest(
    unittest.TestCase
):
    def test_node_writes_flat_structure_list(self):
        domain_result = {
            "status": (
                "adsorbate_structure_generation_completed"
            ),
            "structures": [{
                "adsorption_structure_id": (
                    "S1-CO"
                )
            }],
        }

        with patch(
            "app.graph.nodes.services."
            "adsorbate_structure_builder.build",
            return_value=domain_result,
        ):
            result = (
                adsorbate_structure_generation_node({
                    "task_id": "T1",
                    "adsorption_sites": [{
                        "site_id": "S1",
                    }],
                    "adsorption_reaction_plan": {
                        "formal_adsorbates": ["CO"],
                    },
                    "errors": [],
                })
            )

        self.assertEqual(
            result["adsorption_structures"],
            domain_result["structures"],
        )

    def test_node_records_error_cleanly(self):
        with patch(
            "app.graph.nodes.services."
            "adsorbate_structure_builder.build",
            side_effect=ValueError(
                "coadsorption rejected"
            ),
        ):
            result = (
                adsorbate_structure_generation_node({
                    "task_id": "T1",
                    "adsorption_sites": [{}],
                    "adsorption_reaction_plan": {},
                    "errors": [],
                })
            )

        self.assertEqual(
            result["status"],
            "adsorbate_structure_generation_failed",
        )
        self.assertEqual(
            result["adsorption_structures"],
            [],
        )
        self.assertFalse(
            result[
                "adsorbate_structure_generation"
            ][
                "coadsorption_allowed"
            ]
        )

    def test_result_is_json_serializable(self):
        with patch(
            "app.graph.nodes.services."
            "adsorbate_structure_builder.build",
            return_value={
                "status": (
                    "adsorbate_structure_generation_skipped"
                ),
                "structures": [],
            },
        ):
            result = (
                adsorbate_structure_generation_node({
                    "task_id": "T1",
                    "adsorption_sites": [],
                    "adsorption_reaction_plan": {},
                    "errors": [],
                })
            )

        json.dumps(
            result,
            ensure_ascii=False,
        )


if __name__ == "__main__":
    unittest.main()