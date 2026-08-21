import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import job_monitor_launcher as launcher


def recorded_result():
    return {
        "task_id": "task-01",
        "submission_recording": {
            "status": "submission_jobs_recorded",
            "task_id": "task-01",
            "records": [{"slurm_job_id": "123456"}],
        },
    }


class JobMonitorLauncherTest(unittest.TestCase):
    def test_no_submission_does_not_launch(self):
        result = launcher.launch_job_monitor({"submission_recording": {}})
        self.assertEqual(result["status"], "monitor_not_requested")

    @patch.object(launcher.sys.stdin, "isatty", return_value=True)
    @patch.dict("os.environ", {"JOB_MONITOR_AUTO_OPEN": "false"})
    def test_disabled_does_not_launch(self, _isatty):
        with patch.object(launcher.os, "name", "nt"):
            result = launcher.launch_job_monitor(recorded_result())
        self.assertEqual(result["reason"], "auto_open_disabled")

    @patch.object(launcher.sys.stdin, "isatty", return_value=True)
    @patch.dict(
        "os.environ",
        {"JOB_MONITOR_AUTO_OPEN": "true", "JOB_MONITOR_INTERVAL_SECONDS": "30"},
    )
    def test_launches_one_windows_console(self, _isatty):
        process = Mock(pid=4321)
        with tempfile.TemporaryDirectory() as directory, patch.object(
            launcher, "SESSION_ROOT", Path(directory)
        ), patch.object(launcher.os, "name", "nt"), patch.object(
            launcher, "_running", return_value=False
        ), patch.object(launcher.subprocess, "Popen", return_value=process) as popen:
            result = launcher.launch_job_monitor(recorded_result())
            session = json.loads(Path(result["session_path"]).read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "monitor_launched")
        self.assertEqual(session["monitor_pid"], 4321)
        command = popen.call_args.args[0][-1]
        self.assertIn("app.job_status_watch_cli", command)
        self.assertIn("--job-ids 123456", command)
        self.assertIn("--interval 30", command)

    @patch.object(launcher.sys.stdin, "isatty", return_value=True)
    @patch.dict("os.environ", {"JOB_MONITOR_AUTO_OPEN": "true"})
    def test_existing_monitor_is_not_duplicated(self, _isatty):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "123456.json").write_text(
                json.dumps({"monitor_pid": 4321}), encoding="utf-8"
            )
            with patch.object(launcher, "SESSION_ROOT", root), patch.object(
                launcher.os, "name", "nt"
            ), patch.object(launcher, "_running", return_value=True), patch.object(
                launcher.subprocess, "Popen"
            ) as popen:
                result = launcher.launch_job_monitor(recorded_result())
        self.assertEqual(result["status"], "monitor_already_running")
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
