import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.domain.failure_diagnosis import FailureDiagnosisService, RetryReviewGate
from app.domain.cluster_transport import ClusterTransportError
from app.domain.result_download import ResultDownloadService
from app.domain.slurm_monitor import SlurmMonitorService
from app.domain.submitted_job_repository import SubmittedJobRepository
from app.domain.vasp_completion import VaspCompletionService
from app.domain.vasp_result_parser import VaspResultParser


class JobOperationsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = SubmittedJobRepository(self.root / "jobs")
        self.record = {
            "job_id": "S1", "slurm_job_id": "123456",
            "remote_job_directory": "/work/runs/task-01/S1",
            "submitted_at": "2026-07-23T00:00:00+00:00",
            "submission_status": "submitted", "submission_performed": True,
            "scientific_identity": {
                "calculation_type": "clean_slab_relax",
                "slab_id": "S1",
                "candidate_id": "C1",
                "atom_count": 1,
                "element_order": ["Cu"],
                "composition": {"Cu": 1},
                "energy_field": "final_toten_ev",
                "source_poscar_path": "data/structures/S1.vasp",
                "vasp_config_version": "vasp-slab-v1",
            },
        }
        self.repo.record_submission("task-01", "c10_slab", "digest", [self.record])

    def tearDown(self):
        self.temporary.cleanup()

    def test_squeue_then_sacct(self):
        transport = Mock()
        transport.run.return_value = "RUNNING|00:10|node01"
        result = SlurmMonitorService(self.repo, transport).poll()
        self.assertEqual(result["jobs"][0]["scheduler_state"], "RUNNING")
        transport.run.side_effect = ["", "COMPLETED|01:00|0:0"]
        result = SlurmMonitorService(self.repo, transport).poll()
        self.assertEqual(result["jobs"][0]["scheduler_state"], "COMPLETED")
        self.assertTrue(
            all(
                call.kwargs.get("timeout") == SlurmMonitorService.QUERY_TIMEOUT_SECONDS
                for call in transport.run.call_args_list
            )
        )

    def test_invalid_live_job_id_falls_back_to_sacct(self):
        transport = Mock()
        transport.run.side_effect = [
            ClusterTransportError(
                "Remote command failed: slurm_load_jobs error: "
                "Invalid job id specified"
            ),
            "COMPLETED|01:00|0:0",
        ]
        result = SlurmMonitorService(self.repo, transport).poll()
        self.assertEqual(result["status"], "slurm_monitor_completed")
        self.assertEqual(result["jobs"][0]["scheduler_state"], "COMPLETED")
        self.assertEqual(result["jobs"][0]["scheduler_source"], "sacct")

    def test_completion_requires_vasp_evidence(self):
        self.repo.update("123456", {"scheduler_state": "COMPLETED"})
        transport = Mock()
        transport.validate_remote_child.return_value = "/work/runs/task-01/S1"
        transport.quote.side_effect = lambda value: value
        transport.run.return_value = (
            "outcar=yes\noszicar=yes\ncontcar=yes\nnormal=yes\n"
            "converged=yes\nionic_steps=12"
        )
        result = VaspCompletionService(
            self.repo, transport, "/work/runs"
        ).inspect()
        self.assertEqual(result["jobs"][0]["vasp_decision"], "completed_converged")

    def test_normal_vasp_end_recovers_expired_scheduler_record(self):
        self.repo.update("123456", {"scheduler_state": "RUNNING"})
        transport = Mock()
        transport.validate_remote_child.return_value = "/work/runs/task-01/S1"
        transport.quote.side_effect = lambda value: value
        transport.run.return_value = (
            "outcar=yes\noszicar=yes\ncontcar=yes\nnormal=yes\n"
            "converged=yes\nionic_steps=12"
        )
        result = VaspCompletionService(
            self.repo, transport, "/work/runs"
        ).inspect()
        job = result["jobs"][0]
        self.assertEqual(job["vasp_decision"], "completed_converged")
        self.assertTrue(job["download_eligible"])
        self.assertEqual(job["scheduler_state"], "COMPLETED")
        self.assertTrue(job["scheduler_completion_inferred_from_vasp"])

    def test_download_uses_whitelist(self):
        local_results = self.root / "results"
        self.repo.update("123456", {"download_eligible": True})
        transport = Mock()
        transport.validate_remote_child.return_value = "/work/runs/task-01/S1"
        transport.quote.side_effect = lambda value: value
        transport.run.return_value = "OUTCAR\nOSZICAR\nCONTCAR\n"
        def fake_download(remote, local):
            local.parent.mkdir(parents=True, exist_ok=True)
            content = "data\n"
            if local.name == "CONTCAR":
                content = "title\n1\n1 0 0\n0 1 0\n0 0 1\nCu\n1\nDirect\n0 0 0\n"
            local.write_text(content, encoding="utf-8")
        transport.download.side_effect = fake_download
        service = ResultDownloadService(
            self.repo, transport, local_results, "/work/runs"
        )
        result = service.download({
            "status": "result_download_approved",
            "approved_slurm_job_ids": ["123456"],
            "confirmation_text": "DOWNLOAD 123456",
        })
        names = {item["name"] for item in result["jobs"][0]["downloaded_files"]}
        self.assertEqual(names, {"OUTCAR", "OSZICAR", "CONTCAR"})
        self.assertNotIn("POTCAR", names)

    def test_parser_extracts_energy_and_structure(self):
        root = self.root / "parsed"
        root.mkdir()
        (root / "OUTCAR").write_text(
            "free  energy   TOTEN  = -10.500 eV\n"
            "FORCES: max atom, RMS 0.020 0.010\n"
            "reached required accuracy\n"
            "General timing and accounting informations for this job\n",
            encoding="utf-8",
        )
        (root / "OSZICAR").write_text(
            " 1 F= -.1 E0= -10.400\n", encoding="utf-8"
        )
        (root / "CONTCAR").write_text(
            "title\n1\n1 0 0\n0 1 0\n0 0 1\nCu Co\n1 1\nDirect\n0 0 0\n0 0 0\n",
            encoding="utf-8",
        )
        self.repo.update("123456", {"local_result_directory": str(root)})
        result = VaspResultParser(self.repo).parse()
        parsed = result["jobs"][0]["parsed_vasp_result"]
        self.assertEqual(parsed["final_toten_ev"], -10.5)
        self.assertEqual(parsed["final_structure"]["atom_count"], 2)

    def test_explicit_empty_parser_selection_parses_nothing(self):
        result = VaspResultParser(self.repo).parse([])
        self.assertEqual(result["status"], "vasp_result_parsing_empty")
        self.assertEqual(result["parsed_count"], 0)

    def test_failure_diagnosis_never_retries_automatically(self):
        self.repo.update("123456", {
            "scheduler_state": "OUT_OF_MEMORY",
            "vasp_decision": "failed",
            "last_scheduler_message": "oom-kill",
        })
        result = FailureDiagnosisService(self.repo).diagnose()
        job = result["jobs"][0]
        self.assertEqual(job["failure_diagnosis"]["category"], "out_of_memory")
        self.assertFalse(result["automatic_retry_performed"])
        approved = RetryReviewGate.review(job, {
            "action": "approve_retry_plan",
            "confirmation_text": "RETRY 123456",
        })
        self.assertEqual(approved["status"], "retry_plan_approved")
        self.assertFalse(approved["submission_performed"])
        self.assertFalse(approved["poscar_modified"])


if __name__ == "__main__":
    unittest.main()
