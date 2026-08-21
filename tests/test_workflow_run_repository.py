import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

from app.domain.workflow_run_repository import WorkflowRunRepository


class WorkflowRunRepositoryTest(unittest.TestCase):
    def test_updates_are_durable_and_merge_existing_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = WorkflowRunRepository(Path(temporary))
            repository.update("T1", {
                "workflow_status": "waiting_for_dft_results",
                "active_slurm_jobs": ["123"],
            })
            repository.update("T1", {
                "workflow_status": "ready_for_c8_resume",
            })
            value = repository.get("T1")
            self.assertEqual(value["active_slurm_jobs"], ["123"])
            self.assertEqual(value["workflow_status"], "ready_for_c8_resume")

    def test_concurrent_repository_instances_do_not_lose_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = WorkflowRunRepository(root)
            second = WorkflowRunRepository(root)
            barrier = threading.Barrier(2)

            def write(repository, field):
                barrier.wait()
                repository.update("T2", {field: True})

            threads = [
                threading.Thread(target=write, args=(first, "from_first")),
                threading.Thread(target=write, args=(second, "from_second")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            value = first.get("T2")
            self.assertTrue(value["from_first"])
            self.assertTrue(value["from_second"])

    def test_permission_error_during_replace_is_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = WorkflowRunRepository(Path(temporary))
            real_replace = __import__("os").replace
            calls = 0

            def flaky_replace(source, destination):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PermissionError(5, "temporarily locked")
                return real_replace(source, destination)

            with patch(
                "app.domain.workflow_run_repository.os.replace",
                side_effect=flaky_replace,
            ), patch("app.domain.workflow_run_repository.time.sleep"):
                repository.update("T3", {"status": "running"})

            self.assertEqual(calls, 2)
            self.assertEqual(repository.get("T3")["status"], "running")


if __name__ == "__main__":
    unittest.main()
