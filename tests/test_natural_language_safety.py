import tempfile
import unittest
from pathlib import Path

from app.domain.direct_c_stage import classify_direct_c_stage_request
from app.domain.external_structure_input import ExternalStructureInputService
from app.domain.llm_validation import strict_bool
from app.graph import nodes
from tools.literature.schemas import Assertion, PaperRecord


class NaturalLanguageSafetyTest(unittest.TestCase):
    def test_stage_labels_are_not_formation_energy(self):
        service = ExternalStructureInputService()
        self.assertIsNone(service._energy_from_question("执行 C7 和 C12.7"))

    def test_energy_requires_unit(self):
        service = ExternalStructureInputService()
        self.assertAlmostEqual(
            service._energy_from_question("形成能 -0.05748231 eV/atom"),
            -0.05748231,
        )

    def test_direct_c_extracts_only_explicit_five_metals(self):
        result = classify_direct_c_stage_request(
            "我要构造一个高熵 CuFeNiCoMn 催化剂，执行 C7 和 DFT。"
        )
        self.assertTrue(result["requested"])
        self.assertEqual(result["specified_elements"], ["Cu", "Fe", "Ni", "Co", "Mn"])

    def test_direct_c_does_not_treat_co_or_stage_as_elements(self):
        result = classify_direct_c_stage_request("执行 C7，研究 CO 催化剂")
        self.assertFalse(result["requested"])

    def test_boolean_strings_are_not_truthy(self):
        with self.assertRaises(TypeError):
            strict_bool("false", field="needs_dft")

    def test_literature_string_boolean_is_not_true(self):
        assertion = Assertion.from_dict({
            "kind": "reaction",
            "value": "CO2RR",
            "inferred": "false",
        })
        self.assertFalse(assertion.inferred)

    def test_external_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            request = ExternalStructureInputService().resolve_request(
                "", {"path": directory}
            )
            with self.assertRaises(FileNotFoundError):
                ExternalStructureInputService().prepare(request)

    def test_external_structure_failure_marks_c6_and_c7_not_executed(self):
        result = nodes.external_structure_input_node({
            "external_structure_request": {
                "path": "Z:\\definitely-missing\\POSCAR",
            },
            "errors": [],
        })

        self.assertEqual(result["status"], "external_structure_input_failed")
        self.assertEqual(
            result["formation_energy_evaluation"]["status"], "not_executed"
        )
        self.assertEqual(result["stability_screening"]["status"], "not_executed")
        self.assertEqual(
            result["workflow_stop_reason"], "external_structure_input_failed"
        )


if __name__ == "__main__":
    unittest.main()
