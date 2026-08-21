import unittest

from tools.literature.evidence_quality import EvidenceQualityEvaluator


class EvidenceQualityTest(unittest.TestCase):
    def setUp(self):
        self.evaluator = EvidenceQualityEvaluator()
        self.task = {
            "reaction_family": "CO2RR",
            "target_product": "CO",
            "material_family": "high_entropy_alloy",
        }

    @staticmethod
    def strong_paper() -> dict:
        return {
            "paper_id": "openalex:1",
            "title": "CuFeCoNiMn high-entropy alloy for CO2 reduction to CO",
            "abstract": (
                "The CuFeCoNiMn high-entropy alloy demonstrates selective CO "
                "production with a Faradaic efficiency of 92%."
            ),
            "doi": "10.1000/example",
            "journal": "Example Journal",
            "year": 2025,
            "publication_type": "article",
            "journal_impact_factor": 12.0,
            "journal_metric_year": 2024,
            "journal_metric_source": "Journal Citation Reports",
        }

    def test_three_dimensions_and_journal_impact_are_reported(self):
        result = self.evaluator.evaluate(self.strong_paper(), self.task)

        self.assertEqual(result["quality_score_max"], 100.0)
        self.assertEqual(result["metadata_quality"]["max_score"], 20.0)
        self.assertEqual(result["task_relevance"]["max_score"], 30.0)
        self.assertEqual(result["claim_evidence_quality"]["max_score"], 30.0)
        self.assertEqual(result["journal_impact"]["max_score"], 20.0)
        self.assertEqual(result["journal_impact"]["score"], 16.0)

    def test_explicit_five_metal_hea_is_a_level(self):
        result = self.evaluator.evaluate(self.strong_paper(), self.task)

        self.assertEqual(result["quality_level"], "A")
        self.assertEqual(
            result["composition_elements"], ["Cu", "Fe", "Co", "Ni", "Mn"]
        )
        self.assertTrue(result["hea_composition_eligible"])
        self.assertEqual(
            result["common_hea_transition_metals"],
            ["Co", "Cu", "Fe", "Mn", "Ni"],
        )

    def test_four_metal_hea_is_eligible_without_ratio(self):
        paper = self.strong_paper()
        paper["title"] = "Cu-Fe-Co-Ni high-entropy alloy for CO2 reduction to CO"
        paper["abstract"] = (
            "The Cu Fe Co Ni high-entropy alloy achieves 81% CO selectivity."
        )
        result = self.evaluator.evaluate(paper, self.task)

        self.assertTrue(result["four_or_five_metals"])
        self.assertTrue(result["hea_composition_eligible"])

    def test_high_impact_cannot_replace_composition_evidence(self):
        paper = self.strong_paper()
        paper["title"] = "High-entropy catalysts for CO2 reduction to CO"
        paper["abstract"] = "This review discusses CO2 reduction and CO selectivity."
        paper["journal_impact_factor"] = 50.0
        result = self.evaluator.evaluate(paper, self.task)

        self.assertFalse(result["hea_composition_eligible"])
        self.assertNotEqual(result["quality_level"], "A")

    def test_unverified_impact_factor_receives_zero(self):
        paper = self.strong_paper()
        paper["journal_metric_source"] = ""
        result = self.evaluator.evaluate(paper, self.task)

        self.assertEqual(result["journal_impact"]["score"], 0.0)
        self.assertEqual(result["journal_impact"]["status"], "unavailable")

    def test_retracted_paper_is_always_d_level(self):
        paper = self.strong_paper()
        paper["is_retracted"] = True
        result = self.evaluator.evaluate(paper, self.task)

        self.assertEqual(result["quality_level"], "D")

    def test_co_does_not_match_cobalt(self):
        paper = self.strong_paper()
        paper["title"] = "Cobalt coordination and composition analysis"
        paper["abstract"] = "This work studies cobalt coordination chemistry."
        result = self.evaluator.evaluate(paper, self.task)

        self.assertFalse(result["product_direct"])

    def test_target_product_does_not_affect_score_or_issues(self):
        paper = self.strong_paper()
        paper["title"] = "CuFeCoNiMn high-entropy alloy for CO2 reduction"
        paper["abstract"] = (
            "The CuFeCoNiMn high-entropy alloy demonstrates a current "
            "density of 120 mA cm-2 for CO2 reduction."
        )
        result = self.evaluator.evaluate(paper, self.task)

        self.assertEqual(
            result["task_relevance"]["components"]["target_product"], 0.0
        )
        self.assertFalse(any(
            "target product" in issue.lower()
            for issue in result["issues"]
        ))

    def test_sentence_leading_in_is_not_indium(self):
        elements = self.evaluator._elements_in_text(
            "In this study, Ni-Co-W-Zr(P) medium entropy alloy was tested."
        )
        self.assertNotIn("In", elements)
        self.assertEqual(elements, ["Ni", "Co", "W", "Zr"])

    def test_explicit_lists_and_compact_formula_are_detected(self):
        self.assertEqual(
            self.evaluator._elements_in_text("Fe, Co, Ni, Cr, and Mo"),
            ["Fe", "Co", "Ni", "Cr", "Mo"],
        )
        self.assertEqual(
            self.evaluator._elements_in_text("CuFeCoNiMn"),
            ["Cu", "Fe", "Co", "Ni", "Mn"],
        )

    def test_evaluate_many_preserves_original_fields(self):
        result = self.evaluator.evaluate_many([self.strong_paper()], self.task)
        self.assertEqual(result[0]["paper_id"], "openalex:1")
        self.assertIn("evidence_quality", result[0])


if __name__ == "__main__":
    unittest.main()
