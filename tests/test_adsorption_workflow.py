import unittest

from app.graph.adsorption_workflow import (
    build_adsorption_graph,
)


class AdsorptionWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.graph = build_adsorption_graph()
        self.drawable = self.graph.get_graph()

    def test_contains_c12_1_to_c12_5_nodes(self):
        expected = {
            "adsorption_reaction_planning",
            "adsorption_site_generation",
            "adsorbate_structure_generation",
            "adsorption_structure_quality",
            "adsorption_structure_review",
            "adsorption_dft_preview",
            "adsorption_dft_review",
            "adsorption_dft_revision_plan",
            "adsorption_dft_revision_apply",
            "adsorption_dft_finalize",
        }
        self.assertTrue(expected.issubset(set(self.drawable.nodes)))

    def test_excludes_remote_side_effect_nodes(self):
        forbidden = {
            "remote_upload",
            "remote_submission",
            "submission_record",
            "dft_local_preflight",
        }
        self.assertTrue(forbidden.isdisjoint(set(self.drawable.nodes)))

    def test_revision_cycle_returns_to_review(self):
        edges = {
            (edge.source, edge.target)
            for edge in self.drawable.edges
        }
        self.assertIn(
            (
                "adsorption_dft_revision_apply",
                "adsorption_dft_review",
            ),
            edges,
        )

    def test_finalize_is_the_only_terminal_scientific_node(self):
        terminal_sources = {
            edge.source
            for edge in self.drawable.edges
            if edge.target == "__end__"
        }
        self.assertEqual(
            terminal_sources,
            {"adsorption_dft_finalize"},
        )


if __name__ == "__main__":
    unittest.main()
