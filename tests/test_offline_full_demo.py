from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from langgraph.types import Command

from app.domain.vasp_result_parser import VaspResultParser
from app.graph.adsorption_job_operations import (
    build_adsorption_energy_resume_graph,
)


class OfflineFullDemoTest(unittest.TestCase):
    """Use saved VASP outputs without contacting a real cluster."""

    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    DEMO_ROOT = (
        PROJECT_ROOT
        / "data"
        / "demo_cases"
        / "co_adsorption_validation"
    )

    def _parse_result(
        self,
        directory: Path,
    ) -> dict:
        parser = VaspResultParser()

        return parser._parse_one({
            "local_result_directory": str(
                directory.resolve()
            ),
        })

    def test_saved_vasp_results_enter_c12_7_review(self):
        clean_directory = (
            self.DEMO_ROOT / "clean_slab"
        )
        adsorption_directory = (
            self.DEMO_ROOT / "slab_CO"
        )
        reference_path = (
            self.DEMO_ROOT / "reference.json"
        )

        self.assertTrue(
            (clean_directory / "OUTCAR").is_file()
        )
        self.assertTrue(
            (clean_directory / "CONTCAR").is_file()
        )
        self.assertTrue(
            (adsorption_directory / "OUTCAR").is_file()
        )
        self.assertTrue(
            (adsorption_directory / "CONTCAR").is_file()
        )
        self.assertTrue(reference_path.is_file())

        clean_parsed = self._parse_result(
            clean_directory
        )
        adsorption_parsed = self._parse_result(
            adsorption_directory
        )

        clean_vasp = clean_parsed[
            "parsed_vasp_result"
        ]
        adsorption_vasp = adsorption_parsed[
            "parsed_vasp_result"
        ]

        self.assertTrue(
            clean_vasp["normal_termination"]
        )
        self.assertTrue(
            clean_vasp["required_accuracy_reached"]
        )
        self.assertTrue(
            adsorption_vasp["normal_termination"]
        )
        self.assertTrue(
            adsorption_vasp[
                "required_accuracy_reached"
            ]
        )

        clean_energy = clean_vasp[
            "final_toten_ev"
        ]
        adsorption_energy = adsorption_vasp[
            "final_toten_ev"
        ]

        reference = json.loads(
            reference_path.read_text(
                encoding="utf-8"
            )
        )
        reference_energy = float(
            reference["reference_energy_ev"]
        )

        clean_slab_id = "DEMO-CLEAN-SLAB-001"
        adsorption_structure_id = (
            "DEMO-SLAB-CO-001"
        )

        adsorption_record = {
            "task_id": "offline-demo",
            "job_id": adsorption_structure_id,
            "job_source": "c12_5_adsorption",
            "slurm_job_id": "900002",
            "vasp_decision": (
                "completed_converged"
            ),
            "result_parsing_status": "parsed",
            "parsed_vasp_result": adsorption_vasp,
            "scientific_identity": {
                "calculation_type": (
                    "adsorption_relax"
                ),
                "adsorption_structure_id": (
                    adsorption_structure_id
                ),
                "candidate_id": "DEMO-C1",
                "source_clean_slab_id": (
                    clean_slab_id
                ),
                "site_id": "demo-site-1",
                "site_type": "ontop",
                "adsorbate": "CO",
            },
        }

        initial_state = {
            "task_id": "offline-demo",
            "adsorption_parsed_results": [
                adsorption_record
            ],
            "clean_slab_energies": {
                clean_slab_id: clean_energy,
            },
            "reference_energies": {
                "CO": reference_energy,
            },
            "errors": [],
            "status": "offline_demo_ready",
        }

        graph = build_adsorption_energy_resume_graph()
        config = {
            "configurable": {
                "thread_id": (
                    "offline-demo-"
                    + uuid.uuid4().hex
                ),
            }
        }

        with patch(
            "app.graph.adsorption_job_operations."
            "WorkflowRunRepository.update",
            return_value={
                "task_id": "offline-demo",
                "terminal": True,
            },
        ) as mocked_update:
            first = graph.invoke(
                initial_state,
                config=config,
            )

            self.assertIn("__interrupt__", first)

            request = first["__interrupt__"][0].value
            self.assertEqual(
                request["type"],
                "adsorption_energy_review_required",
            )

            calculations = request["calculations"]
            self.assertEqual(len(calculations), 1)

            calculation = calculations[0]
            calculated_energy = calculation[
                "adsorption_energy_ev"
            ]

            expected_energy = (
                adsorption_energy
                - clean_energy
                - reference_energy
            )

            self.assertAlmostEqual(
                calculated_energy,
                expected_energy,
                places=8,
            )

            final = graph.invoke(
                Command(
                    resume={
                        "approve": [
                            calculation[
                                "adsorption_energy_id"
                            ]
                        ],
                        "reject": [],
                        "defer": [],
                        "note": (
                            "Offline demonstration "
                            "calculation checked."
                        ),
                    }
                ),
                config=config,
            )

        self.assertEqual(
            final["status"],
            "adsorption_energy_review_completed",
        )
        self.assertEqual(
            len(
                final[
                    "approved_adsorption_energies"
                ]
            ),
            1,
        )

        persisted_changes = (
            mocked_update.call_args.args[1]
        )
        self.assertTrue(
            persisted_changes["terminal"]
        )
        self.assertIsNone(
            persisted_changes["resume_stage"]
        )

        print()
        print("=" * 70)
        print("OFFLINE ABC DEMO RESULT")
        print("=" * 70)
        print(
            json.dumps(
                {
                    "real_cluster_contacted": False,
                    "real_submission_performed": False,
                    "clean_slab_energy_ev": (
                        clean_energy
                    ),
                    "adsorbed_energy_ev": (
                        adsorption_energy
                    ),
                    "reference_energy_ev": (
                        reference_energy
                    ),
                    "operation": (
                        "adsorbed - clean - reference"
                    ),
                    "adsorption_energy_ev": (
                        calculated_energy
                    ),
                    "review_status": final[
                        "status"
                    ],
                    "scientific_warning": (
                        reference.get("note", "")
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    unittest.main()