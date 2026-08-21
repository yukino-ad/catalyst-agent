from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from langgraph.types import Command

from app.api.state_presenter import safe_interrupt
from app.api.task_manager import TaskManager
from app.api.workflow_timeline import create_timeline
from app.domain.workflow_run_repository import WorkflowRunRepository


class ImmediateExecutor:
    def submit(self, function, *args):
        function(*args)


class FakeGraph:
    def __init__(self, interrupt=None):
        self.interrupt = interrupt

    def stream(self, initial_state, config, stream_mode):
        yield {"task_analysis": {"status": "task_analysis_completed"}}
        if self.interrupt:
            yield {"__interrupt__": [SimpleNamespace(value=self.interrupt)]}

    def get_state(self, config):
        return SimpleNamespace(values={"status": "task_analysis_completed"})


class ResumableFakeGraph(FakeGraph):
    def __init__(self):
        super().__init__({
            "type": "candidate_review_required",
            "message": "Review candidates",
            "max_selected": 1,
            "candidates": [{"candidate_id": "C1", "elements": ["Cu"]}],
        })
        self.resume_inputs = []

    def stream(self, graph_input, config, stream_mode):
        if isinstance(graph_input, Command):
            self.resume_inputs.append((graph_input, config))
            yield {"structure_modeling": {"status": "completed"}}
            return
        yield from super().stream(graph_input, config, stream_mode)


class FailedReviewGraph(FakeGraph):
    def stream(self, initial_state, config, stream_mode):
        yield {"literature_review": {"status": "literature_review_failed"}}

    def get_state(self, config):
        return SimpleNamespace(values={
            "status": "literature_summarized",
            "literature_review": {"status": "review_failed"},
            "errors": [{"node": "literature_review", "message": "Invalid assertion IDs"}],
        })


class PauseResumeGraph(FakeGraph):
    def __init__(self, repository, task_id_holder):
        super().__init__()
        self.repository = repository
        self.task_id_holder = task_id_holder
        self.inputs = []

    def stream(self, graph_input, config, stream_mode):
        self.inputs.append(graph_input)
        if graph_input is None:
            yield {"capability_gate": {"status": "capability_checked"}}
            return
        task_id = config["configurable"]["thread_id"]
        self.repository.update(task_id, {"consultation_pause_requested": True})
        yield {"task_analysis": {"status": "task_analysis_completed"}}

    def get_state(self, config):
        return SimpleNamespace(values={"status": "task_analysis_completed"}, next=("capability_gate",))


class ApiTaskManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        repository = WorkflowRunRepository(Path(self.temp.name) / "runs")
        self.repository = repository

    def tearDown(self):
        self.temp.cleanup()

    def test_task_completes_and_is_persisted(self):
        manager = TaskManager(
            repository=self.repository,
            graph=FakeGraph(),
            executor=ImmediateExecutor(),
        )
        created = manager.create("测试自然语言任务")
        record = manager.get(created["task_id"])

        self.assertEqual(record["workflow_status"], "completed")
        self.assertEqual(record["progress"], 100)
        self.assertFalse(record["remote_operations_allowed"])

    def test_consultation_pauses_at_node_boundary_and_continues_checkpoint(self):
        graph = PauseResumeGraph(self.repository, {})
        manager = TaskManager(
            repository=self.repository,
            graph=graph,
            executor=ImmediateExecutor(),
        )
        created = manager.create("测试节点边界暂停")
        task_id = created["task_id"]
        paused = manager.get(task_id)
        consultation = {
            "consultation_id": "consult-pause",
            "continued": False,
        }
        self.repository.update(task_id, {
            "workflow_status": "paused_for_consultation",
            "consultation_history": [consultation],
            "active_consultation": consultation,
            "consultation_pending_continue": True,
            "workflow_status_before_consultation": "running",
        })

        self.assertEqual(paused["workflow_status"], "paused_for_consultation")
        manager.continue_after_consultation(task_id, "consult-pause")
        completed = manager.get(task_id)
        self.assertEqual(completed["workflow_status"], "completed")
        self.assertIsNone(graph.inputs[-1])

    def test_interrupt_is_persisted_without_full_payload(self):
        manager = TaskManager(
            repository=self.repository,
            graph=FakeGraph({
                "type": "candidate_review_required",
                "message": "Review candidates",
                "candidates": [{"candidate_id": "C1", "secret": "hidden"}],
            }),
            executor=ImmediateExecutor(),
        )
        created = manager.create("测试人工门")
        record = manager.get(created["task_id"])

        self.assertEqual(record["workflow_status"], "waiting_for_human")
        self.assertEqual(record["review_type"], "candidate_review_required")
        self.assertEqual(record["review"]["candidate_ids"], ["C1"])
        self.assertNotIn("secret", str(record["review"]))

    def test_terminal_node_failure_is_not_reported_as_completed(self):
        manager = TaskManager(
            repository=self.repository,
            graph=FailedReviewGraph(),
            executor=ImmediateExecutor(),
        )
        created = manager.create("测试审查失败终态")
        record = manager.get(created["task_id"])
        self.assertEqual(record["workflow_status"], "failed")
        self.assertEqual(record["stage"], "literature_review")
        self.assertIn("Invalid assertion IDs", record["error"])

    def test_safe_interrupt_exposes_only_reviewable_vasp_previews(self):
        result = safe_interrupt({
            "type": "dft_input_review_required",
            "bundles": [{
                "bundle_id": "B1",
                "preview": {
                    "POSCAR": "POSCAR text",
                    "INCAR": "ENCUT = 500",
                    "KPOINTS": "Gamma",
                    "POTCAR": [{
                        "element": "Co",
                        "potential": "Co_pv",
                        "source_path": "sensitive/path/POTCAR",
                        "sha256": "secret-digest",
                    }],
                    "vasp.slurm": {
                        "job_name": "B1",
                        "nodes": 1,
                        "command": "vasp_std",
                        "full_text": "sensitive full script",
                    },
                },
            }],
        })
        self.assertEqual(result["bundle_ids"], ["B1"])
        preview = result["items"][0]["file_previews"]
        self.assertEqual(preview["INCAR"], "ENCUT = 500")
        self.assertEqual(preview["POTCAR"], [{"element": "Co", "potential": "Co_pv"}])
        self.assertNotIn("sensitive", str(result))
        self.assertNotIn("secret-digest", str(result))

    def test_dft_execution_interrupt_has_three_safe_options(self):
        result = safe_interrupt({
            "type": "dft_execution_options_required",
            "job_source": "c10_slab",
            "job_count": 1,
            "jobs": [{"job_id": "J1", "job_dir": "private/path"}],
            "choices": [
                {"value": "relax_only", "label": "仅弛豫", "description": "弛豫"},
                {"value": "relax_then_static", "label": "弛豫加静态单点"},
                {"value": "defer", "label": "暂不提交"},
            ],
        })
        self.assertEqual(result["title"], "C11 DFT 计算方式选择")
        self.assertEqual([item["mode"] for item in result["options"]], [
            "relax_only", "relax_then_static", "defer",
        ])
        self.assertNotIn("private/path", str(result))

    def test_legacy_dft_execution_interrupt_gets_safe_options(self):
        result = safe_interrupt({
            "type": "dft_execution_options_required",
            "job_source": "c10_slab",
            "job_count": 1,
            "jobs": [{"job_id": "J1"}],
        })
        self.assertEqual(
            [item["mode"] for item in result["options"]],
            ["relax_only", "relax_then_static", "defer"],
        )

    def test_legacy_persisted_dft_review_is_normalized_on_read(self):
        manager = TaskManager(repository=self.repository, graph=FakeGraph(), executor=ImmediateExecutor())
        self.repository.update("legacy-c11", {
            "workflow_status": "waiting_for_human",
            "review_type": "dft_execution_options_required",
            "review": {"type": "dft_execution_options_required", "job_count": 1},
        })
        record = manager.get("legacy-c11")
        self.assertEqual(len(record["review"]["options"]), 3)

    def test_fcc_only_task_explains_skipped_scientific_stages(self):
        manager = TaskManager(repository=self.repository, graph=FakeGraph(), executor=ImmediateExecutor())
        timeline = create_timeline()
        for stage in timeline:
            if stage["stage_id"] == "C5":
                stage["status"] = "completed"
            elif stage["stage_id"].startswith(("C6", "C7", "C8", "C9", "C10", "C11", "C12")):
                stage["status"] = "skipped"
                stage["skip_reason"] = "Workflow completed."
        self.repository.update("fcc-only", {
            "workflow_status": "completed",
            "message": "工作流已完成。",
            "workflow_timeline": timeline,
            "review_history": [{
                "review_type": "c_stage_execution_review_required",
                "decision": {"mode": "fcc_only"},
            }],
        })
        record = manager.get("fcc-only")
        c6 = next(item for item in record["workflow_timeline"] if item["stage_id"] == "C6")
        self.assertIn("仅进行 FCC bulk 建模", c6["skip_reason"])
        self.assertIn("未执行形成能预测", record["message"])

    def test_completed_legacy_c12_task_gets_frontend_timeline(self):
        manager = TaskManager(
            repository=self.repository,
            graph=FakeGraph(),
            executor=ImmediateExecutor(),
        )
        self.repository.update("legacy-c12", {
            "workflow_status": "adsorption_energy_review_completed",
            "terminal": True,
            "selected_adsorbate": "CO",
            "adsorption_source_slabs": {
                "slab_id": "slab-1",
                "clean_slab_slurm_job_id": "100",
                "clean_slab_energy_ev": -10.0,
            },
            "adsorption_dft_jobs": [{
                "job_id": "slab-1-CO",
                "adsorption_structure_id": "slab-1-CO",
                "adsorbate": "CO",
                "site_type": "bridge",
                "scientific_identity": {"atom_count": 50},
            }],
            "adsorption_parsed_results": {
                "slurm_job_id": "101",
                "scheduler_state": "COMPLETED",
                "vasp_decision": "completed_converged",
                "parsed_vasp_result": {"final_toten_ev": -20.0},
            },
            "adsorption_energy_calculation": {
                "calculations": [{
                    "adsorption_energy_id": "AE-1",
                    "adsorption_structure_id": "slab-1-CO",
                    "adsorbate": "CO",
                    "adsorption_energy_ev": -1.2,
                    "energy_unit": "eV",
                    "calculation": {
                        "adsorbed_energy_ev": -20.0,
                        "clean_slab_energy_ev": -10.0,
                        "reference_energy_ev": -8.8,
                        "substitution": "-20 - (-10) - (-8.8)",
                    },
                }],
            },
            "adsorption_energy_review": {
                "approved_count": 1,
                "decision": {"approve": ["AE-1"], "reject": [], "defer": []},
            },
        })
        record = manager.get("legacy-c12")
        self.assertEqual(record["workflow_status"], "completed")
        self.assertEqual(record["progress"], 100)
        self.assertEqual(record["stage_label"], "C12.7 吸附能审查已完成")
        c12 = [stage for stage in record["workflow_timeline"] if stage["group"] == "C12"]
        self.assertEqual(len(c12), 7)
        self.assertTrue(all(stage["status"] == "completed" for stage in c12))
        self.assertEqual(record["review_history"][0]["status"], "submitted")

    def test_review_resumes_same_task_and_is_idempotent(self):
        graph = ResumableFakeGraph()
        manager = TaskManager(
            repository=self.repository,
            graph=graph,
            executor=ImmediateExecutor(),
        )
        created = manager.create("测试候选审查恢复")
        task_id = created["task_id"]
        waiting = manager.get(task_id)
        review = waiting["review"]

        manager.submit_review(
            task_id=task_id,
            review_id=review["review_id"],
            review_type="candidate_review_required",
            decision={"select": ["C1"]},
            idempotency_key="same-decision-key",
        )
        completed = manager.get(task_id)
        self.assertEqual(completed["workflow_status"], "completed")
        self.assertEqual(len(graph.resume_inputs), 1)
        self.assertEqual(len(completed["review_history"]), 1)
        self.assertEqual(completed["review_history"][0]["status"], "submitted")
        self.assertEqual(completed["review_history"][0]["decision"]["select"], ["C1"])
        self.assertTrue(completed["stage_events"])
        self.assertEqual(
            graph.resume_inputs[0][1]["configurable"]["thread_id"],
            task_id,
        )

        manager.submit_review(
            task_id=task_id,
            review_id=review["review_id"],
            review_type="candidate_review_required",
            decision={"select": ["C1"]},
            idempotency_key="same-decision-key",
        )
        self.assertEqual(len(graph.resume_inputs), 1)

    def test_legacy_waiting_review_is_added_to_history_on_submit(self):
        graph = ResumableFakeGraph()
        manager = TaskManager(
            repository=self.repository,
            graph=graph,
            executor=ImmediateExecutor(),
        )
        created = manager.create("测试旧任务审查兼容")
        task_id = created["task_id"]
        waiting = manager.get(task_id)
        review = waiting["review"]
        self.repository.update(task_id, {"review_history": []})

        manager.submit_review(
            task_id=task_id,
            review_id=review["review_id"],
            review_type="candidate_review_required",
            decision={"select": ["C1"]},
            idempotency_key="legacy-decision-key",
        )

        completed = manager.get(task_id)
        self.assertEqual(len(completed["review_history"]), 1)
        self.assertEqual(completed["review_history"][0]["status"], "submitted")
        self.assertEqual(completed["review_history"][0]["decision"]["select"], ["C1"])


if __name__ == "__main__":
    unittest.main()
