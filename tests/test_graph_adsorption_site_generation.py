import json
import unittest
from unittest.mock import patch

from app.graph.nodes import adsorption_site_generation_node


class GraphAdsorptionSiteGenerationTest(unittest.TestCase):
    def test_node_writes_flat_sites_and_warnings(self):
        domain_result = {
            "status": "adsorption_site_generation_completed",
            "sites": [{"site_id": "S1-ontop-001"}],
            "warnings": ["site limit applied"],
        }
        with patch(
            "app.graph.nodes.services.adsorption_site_generation_service.generate",
            return_value=domain_result,
        ) as mocked:
            result = adsorption_site_generation_node({
                "adsorption_source_slabs": [{"slab_id": "S1"}],
                "adsorption_reaction_plan": {
                    "ready_for_site_generation": True
                },
                "warnings": ["existing"],
                "errors": [],
            })
        mocked.assert_called_once()
        self.assertEqual(result["adsorption_sites"], domain_result["sites"])
        self.assertEqual(result["warnings"], ["existing", "site limit applied"])

    def test_node_records_domain_exception_cleanly(self):
        with patch(
            "app.graph.nodes.services.adsorption_site_generation_service.generate",
            side_effect=ValueError("invalid CONTCAR"),
        ):
            result = adsorption_site_generation_node({
                "adsorption_source_slabs": [{}],
                "adsorption_reaction_plan": {},
                "warnings": [],
                "errors": [],
            })
        self.assertEqual(result["status"], "adsorption_site_generation_failed")
        self.assertEqual(result["adsorption_sites"], [])
        self.assertFalse(
            result["adsorption_site_generation"]["original_slab_fallback_allowed"]
        )
        self.assertEqual(len(result["errors"]), 1)

    def test_node_result_is_json_serializable(self):
        with patch(
            "app.graph.nodes.services.adsorption_site_generation_service.generate",
            return_value={
                "status": "adsorption_site_generation_skipped",
                "sites": [],
                "warnings": [],
            },
        ):
            result = adsorption_site_generation_node({
                "adsorption_source_slabs": [],
                "adsorption_reaction_plan": {},
                "warnings": [],
                "errors": [],
            })
        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
