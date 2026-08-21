from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.domain.task_report import TaskReportService
from app.domain.workflow_run_repository import WorkflowRunRepository


class OfflineLLM:
    available = False


class EmptyAssets:
    def list_files(self, task_id):
        return []

    def list_structures(self, task_id):
        return []


class EmptyJobs:
    def list_for_task(self, task_id):
        return []


class TaskReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.repository = WorkflowRunRepository(root / "runs")
        self.service = TaskReportService(
            repository=self.repository,
            assets=EmptyAssets(),
            jobs=EmptyJobs(),
            llm=OfflineLLM(),
            root=root / "reports",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_report_persists_three_formats_and_never_invents_dft_results(self):
        self.repository.update("report-task", {
            "question": "测试任务",
            "workflow_status": "completed",
            "stage": "completed",
            "message": "完成",
            "workflow_timeline": [{
                "stage_id": "C6",
                "stage_label": "预测形成能",
                "status": "completed",
                "summary": "CGCNN 预筛完成",
                "outputs": {"formation_energy_ev_per_atom": -0.05},
            }],
            "review_history": [{
                "review_id": "review-1",
                "source_path": "C:/private/POSCAR",
                "api_key": "secret-value",
            }],
            "consultation_history": [],
        })
        metadata = self.service.generate("report-task")
        payload = json.loads(
            self.service.path("report-task", "json").read_text(encoding="utf-8")
        )

        self.assertEqual(metadata["formats"], ["html", "md", "json"])
        self.assertEqual(payload["dft_jobs"], [])
        self.assertNotIn("C:/private", str(payload))
        self.assertNotIn("secret-value", str(payload))
        self.assertIn("E_ads", payload["scientific_formulas"]["adsorption_energy"])
        self.assertEqual(payload["kimi_recommendations"]["source"], "local_rules")
        markdown = self.service.path("report-task", "md").read_text(encoding="utf-8")
        self.assertIn("未获得 task_id 关联的 DFT 作业记录", markdown)


if __name__ == "__main__":
    unittest.main()
