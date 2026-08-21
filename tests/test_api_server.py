from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.server import app


class ApiServerTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch.dict("os.environ", {"WEB_REMOTE_OPERATIONS_ENABLED": "false"})
    def test_health_hides_credentials_and_disables_remote_operations(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["remote_write_enabled"])
        self.assertFalse(payload["submission_enabled"])
        self.assertNotIn("api_key", payload)
        self.assertNotIn("ssh_key_path", payload)

    @patch("app.api.server.task_manager")
    def test_create_and_read_task(self, manager):
        manager.create.return_value = {"task_id": "web-test"}
        manager.get.return_value = {
            "task_id": "web-test",
            "question": "测试",
            "workflow_status": "running",
            "stage": "task_analysis",
            "stage_label": "A1 正在理解自然语言任务",
            "progress": 6,
            "stage_events": [{"event_id": "A1:test", "stage": {"stage_id": "A1"}}],
            "review_history": [{"review_id": "review-test", "status": "submitted"}],
        }
        created = self.client.post("/api/tasks", json={"question": "测试"})
        status = self.client.get("/api/tasks/web-test")

        self.assertEqual(created.status_code, 202)
        self.assertEqual(created.json()["task_id"], "web-test")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["stage"], "task_analysis")
        self.assertEqual(len(status.json()["stage_events"]), 1)
        self.assertEqual(len(status.json()["review_history"]), 1)

    @patch("app.api.server.task_manager")
    def test_unknown_task_returns_404(self, manager):
        manager.get.return_value = None
        response = self.client.get("/api/tasks/missing")
        self.assertEqual(response.status_code, 404)

    @patch("app.api.server.workflow_consultation")
    def test_conversation_route_returns_task_aware_consultation(self, consultation):
        consultation.respond.return_value = {
            "intent": "scientific_explanation",
            "answer": "形成能解释",
            "create_workflow": False,
            "requires_continue_confirmation": True,
        }
        response = self.client.post(
            "/api/conversations/respond",
            json={"question": "形成能是什么", "task_id": "web-test"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "形成能解释")
        consultation.respond.assert_called_once_with("形成能是什么", "web-test")

    @patch("app.api.server.task_reports")
    def test_report_routes_generate_and_return_metadata(self, reports):
        reports.generate.return_value = {
            "task_id": "web-test",
            "status": "ready",
            "formats": ["html", "md", "json"],
        }
        response = self.client.post("/api/tasks/web-test/report")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")

    @patch("app.api.server.task_manager")
    def test_submit_review_returns_resume_location(self, manager):
        manager.submit_review.return_value = {"workflow_status": "resuming"}
        response = self.client.post(
            "/api/tasks/web-test/reviews",
            json={
                "review_id": "review-12345678",
                "review_type": "candidate_review_required",
                "decision": {"select": ["C1"]},
                "idempotency_key": "idempotency-12345678",
            },
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "resuming")
        manager.submit_review.assert_called_once()

    @patch("app.api.server.task_manager")
    def test_invalid_review_returns_conflict(self, manager):
        manager.submit_review.side_effect = ValueError("Unknown review identifiers")
        response = self.client.post(
            "/api/tasks/web-test/reviews",
            json={
                "review_id": "review-12345678",
                "review_type": "candidate_review_required",
                "decision": {"select": ["C99"]},
                "idempotency_key": "idempotency-12345678",
            },
        )
        self.assertEqual(response.status_code, 409)

    @patch("app.api.server.task_manager")
    def test_list_resume_and_archive_task_routes(self, manager):
        manager.list.return_value = [{
            "task_id": "web-history",
            "question": "历史任务",
            "workflow_status": "waiting_for_human",
            "stage": "slab_review_required",
            "stage_label": "C9 slab 审查",
            "progress": 88,
        }]
        manager.resume_plan.return_value = {
            "status": "waiting_for_human",
            "target": "current_review",
            "message": "任务已恢复到当前人工审查卡。",
        }
        manager.archive.return_value = {"task_id": "web-history", "archived": True}

        listed = self.client.get("/api/tasks")
        resumed = self.client.post("/api/tasks/web-history/resume")
        archived = self.client.post("/api/tasks/web-history/archive")

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["tasks"][0]["task_id"], "web-history")
        self.assertEqual(resumed.json()["target"], "current_review")
        self.assertEqual(archived.json()["status"], "archived")

    @patch("app.api.server.research_assets")
    def test_file_routes_never_download_potcar(self, assets):
        assets.list_files.return_value = [{
            "file_id": "safe-file",
            "name": "POTCAR",
            "label": "POTCAR",
            "suffix": "",
            "category": "DFT 输入",
            "size_bytes": 100,
            "previewable": True,
            "downloadable": False,
            "structure": False,
        }]
        assets.downloadable.side_effect = ValueError("POTCAR download is disabled")
        listed = self.client.get("/api/tasks/web-test/files")
        blocked = self.client.get("/api/tasks/web-test/files/safe-file/download")
        self.assertEqual(listed.status_code, 200)
        self.assertFalse(listed.json()["files"][0]["downloadable"])
        self.assertEqual(blocked.status_code, 403)

    @patch("app.api.server.task_manager")
    @patch("app.api.server.job_monitor")
    def test_job_routes_are_read_only_queries(self, monitor, manager):
        manager.get.return_value = {"task_id": "web-test"}
        monitor.list_for_task.return_value = [{
            "slurm_job_id": "12345",
            "scheduler_state": "RUNNING",
        }]
        monitor.get.return_value = monitor.list_for_task.return_value[0]
        listed = self.client.get("/api/tasks/web-test/jobs")
        detail = self.client.get("/api/jobs/12345")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(detail.json()["scheduler_state"], "RUNNING")


if __name__ == "__main__":
    unittest.main()
