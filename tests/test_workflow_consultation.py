from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.api.workflow_timeline import create_timeline
from app.domain.workflow_consultation import WorkflowConsultationService
from app.domain.workflow_run_repository import WorkflowRunRepository


class OfflineLLM:
    available = False


class WorkflowConsultationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = WorkflowRunRepository(Path(self.temp.name) / "runs")
        self.service = WorkflowConsultationService(
            repository=self.repository,
            llm=OfflineLLM(),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_scientific_question_uses_local_rules_and_preserves_task_facts(self):
        self.repository.update("task-1", {
            "question": "构建 CuFeNiCoMn",
            "workflow_status": "running",
            "stage": "formation_energy",
            "stage_label": "C6 形成能",
            "workflow_timeline": create_timeline(),
            "formation_energy_ev_per_atom": -0.12,
        })
        result = self.service.respond("形成能是什么？", "task-1")
        record = self.repository.get("task-1")

        self.assertEqual(result["intent"], "scientific_explanation")
        self.assertEqual(result["answer_source"], "local_rules")
        self.assertTrue(result["requires_continue_confirmation"])
        self.assertTrue(record["consultation_pause_requested"])
        self.assertEqual(record["formation_energy_ev_per_atom"], -0.12)

    def test_completed_task_consultation_requires_acknowledgement_without_pause(self):
        self.repository.update("task-2", {
            "workflow_status": "completed",
            "stage": "completed",
            "workflow_timeline": create_timeline(),
        })
        result = self.service.respond("请解释吸附能", "task-2")
        record = self.repository.get("task-2")

        self.assertTrue(result["requires_continue_confirmation"])
        self.assertTrue(record["consultation_pending_continue"])
        self.assertFalse(record["consultation_pause_requested"])
        self.assertEqual(record["workflow_status"], "completed")

    def test_no_task_workflow_command_requests_creation(self):
        result = self.service.respond("请帮我构建 CuFeNiCoMn 高熵合金")
        self.assertEqual(result["intent"], "workflow_command")
        self.assertTrue(result["create_workflow"])


if __name__ == "__main__":
    unittest.main()
