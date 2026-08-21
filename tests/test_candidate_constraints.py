import unittest

from app.domain.candidate_constraints import (
    CandidateConstraintBuilder,
)


class CandidateConstraintBuilderTest(unittest.TestCase):
    def setUp(self):
        self.builder = CandidateConstraintBuilder()
        self.task = {
            "reaction_id": "CO2RR_CO",
            "reaction_family": "CO2RR",
            "target_product": "CO",
            "material_family": "高熵催化剂",
        }

    def test_default_model_does_not_require_cu(self):
        result = self.builder.build(self.task)

        self.assertEqual(
            result["candidate_space"]["required_elements"],
            [],
        )
        self.assertEqual(result["schema_version"], "c1.1")
        self.assertEqual(
            result["structure_rules"]["total_atoms"],
            32,
        )

    def test_user_can_explicitly_require_cu(self):
        result = self.builder.build(
            self.task,
            user_overrides={"required_elements": ["Cu"]},
        )

        self.assertEqual(
            result["candidate_space"]["required_elements"],
            ["Cu"],
        )

    def test_explicit_literature_elements_are_only_preferred(self):
        papers = [{
            "evidence_id": "E1",
            "paper_id": "openalex:1",
            "title": "Example HEA paper",
            "doi": "10.1000/example",
            "review_status": "accepted",
            "assertions": [{
                "kind": "element_set",
                "value": ["Au", "Ag", "Pt", "Pd", "Cu"],
                "evidence_level": "explicit",
                "inferred": False,
            }],
        }]

        result = self.builder.build(
            self.task,
            accepted_papers=papers,
        )
        space = result["candidate_space"]

        self.assertEqual(space["required_elements"], [])
        self.assertEqual(
            space["preferred_elements"],
            ["Au", "Ag", "Pt", "Pd", "Cu"],
        )
        self.assertEqual(result["evidence"][0]["evidence_id"], "E1")

    def test_inferred_elements_need_review(self):
        papers = [{
            "evidence_id": "E1",
            "review_status": "accepted",
            "assertions": [{
                "kind": "element_set",
                "value": ["Ni", "Co"],
                "evidence_level": "inferred",
                "inferred": True,
            }],
        }]

        result = self.builder.build(
            self.task,
            accepted_papers=papers,
        )
        space = result["candidate_space"]

        self.assertEqual(space["preferred_elements"], [])
        self.assertEqual(
            space["inferred_elements_pending_review"],
            ["Ni", "Co"],
        )

    def test_cu_can_be_excluded_when_not_required(self):
        result = self.builder.build(
            self.task,
            user_overrides={"excluded_elements": ["Cu"]},
        )

        self.assertNotIn(
            "Cu",
            result["candidate_space"]["allowed_elements"],
        )

    def test_required_and_excluded_conflict(self):
        with self.assertRaisesRegex(ValueError, "必选和禁用"):
            self.builder.build(
                self.task,
                user_overrides={
                    "required_elements": ["Cu"],
                    "excluded_elements": ["Cu"],
                },
            )

    def test_with_cu_and_p_block_composition(self):
        composition = self.builder.build_composition(
            ["Cu", "Al", "Fe", "Co", "Ni"]
        )

        self.assertEqual(
            composition,
            {"Cu": 8, "Al": 3, "Fe": 7, "Co": 7, "Ni": 7},
        )
        self.assertEqual(sum(composition.values()), 32)

    def test_with_cu_without_p_block_composition(self):
        composition = self.builder.build_composition(
            ["Cu", "Fe", "Co", "Ni", "Mn"]
        )

        self.assertEqual(
            composition,
            {"Cu": 8, "Fe": 6, "Co": 6, "Ni": 6, "Mn": 6},
        )

    def test_without_cu_with_p_block_composition(self):
        composition = self.builder.build_composition(
            ["Al", "Fe", "Co", "Ni", "Mn"]
        )

        self.assertEqual(
            composition,
            {"Al": 4, "Fe": 7, "Co": 7, "Ni": 7, "Mn": 7},
        )

    def test_without_cu_without_p_block_uses_rotating_near_equal_rule(self):
        elements = ["Fe", "Co", "Ni", "Mn", "Mo"]

        first = self.builder.build_composition(elements, variant_index=0)
        second = self.builder.build_composition(elements, variant_index=1)

        self.assertEqual(
            first,
            {"Fe": 7, "Co": 7, "Ni": 6, "Mn": 6, "Mo": 6},
        )
        self.assertEqual(
            second,
            {"Fe": 6, "Co": 7, "Ni": 7, "Mn": 6, "Mo": 6},
        )
        self.assertEqual(sum(first.values()), 32)
        self.assertEqual(sum(second.values()), 32)

    def test_more_than_one_p_block_element_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "最多只能包含一个"):
            self.builder.build_composition(
                ["Al", "Zn", "Fe", "Co", "Ni"]
            )

    def test_unknown_element_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不支持元素"):
            self.builder.build(
                self.task,
                user_overrides={"preferred_elements": ["Hg"]},
            )

    def test_evaluation_dimensions_match_new_stage_boundaries(self):
        result = self.builder.build(self.task)

        self.assertEqual(
            set(result["evaluation_dimensions"]),
            {
                "literature_support",
                "constraint_preference",
                "element_abundance",
                "price",
                "toxicity_environment",
                "synthesis_difficulty",
            },
        )
        self.assertEqual(
            result["deferred_post_structure_evaluation"][
                "formation_energy"
            ],
            "c6",
        )
        self.assertEqual(
            result["deferred_post_structure_evaluation"]["omega"],
            "c7",
        )


if __name__ == "__main__":
    unittest.main()
