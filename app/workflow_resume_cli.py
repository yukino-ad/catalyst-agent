from __future__ import annotations

import argparse
import json
import re
from typing import Any

from langgraph.types import Command

from app.cluster_jobs_cli import (
    collect_download,
    collect_retry,
)
from app.domain.workflow_run_repository import (
    WorkflowRunRepository,
)
from app.graph.adsorption_execution_workflow import (
    adsorption_execution_graph,
)
from app.graph.adsorption_job_operations import (
    adsorption_energy_resume_graph,
    adsorption_job_operations_graph,
)
from app.graph.cli import (
    collect_adsorption_dft_execution,
    collect_adsorption_energy_review,
    collect_adsorption_intermediate_review,
    collect_adsorption_structure_review,
    collect_dft_input_review_decision,
    collect_remote_submission_review,
    collect_remote_upload_review,
    collect_slab_review_decision,
)
from app.graph.job_operations import (
    job_operations_graph,
)


SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9._-]+$")

JOB_OPERATION_STAGES = {
    "formation_energy_backfill",
    "slab_generation",
    "c8_slab_generation",
    "c9_slab_quality",
    "c9_slab_review",
    "c10_dft_preview",
    "c10_dft_review",
    "c10_dft_finalize",
    "c11.5.2_clean_slab_result_monitoring",
    "c12.1_adsorption_planning",
}

ADSORPTION_SUBMISSION_STAGE = (
    "c12.6_adsorption_submission"
)
ADSORPTION_MONITORING_STAGE = (
    "c12.6_adsorption_result_monitoring"
)
ADSORPTION_ENERGY_STAGE = (
    "c12.7_adsorption_energy"
)


def show(title: str, value: Any) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def load_workflow(
    task_id: str,
    repository: WorkflowRunRepository | None = None,
) -> dict[str, Any]:
    task_id = str(task_id).strip()
    if not SAFE_TASK_ID.fullmatch(task_id):
        raise ValueError(
            "task_id may contain letters, digits, '.', '_' and '-' only"
        )

    value = (repository or WorkflowRunRepository()).get(task_id)
    if value is None:
        raise FileNotFoundError(
            f"Workflow record does not exist for task_id: {task_id}"
        )
    if not isinstance(value, dict):
        raise TypeError("Workflow record must be a JSON object")
    return value


def resolve_resume_target(workflow: dict[str, Any]) -> str:
    if workflow.get("terminal") is True:
        return "complete"

    stage = str(workflow.get("resume_stage", "")).strip()
    if stage in JOB_OPERATION_STAGES:
        return "job_operations"
    if stage == ADSORPTION_SUBMISSION_STAGE:
        return "adsorption_submission"
    if stage == ADSORPTION_MONITORING_STAGE:
        return "adsorption_monitoring"
    if stage == ADSORPTION_ENERGY_STAGE:
        return "adsorption_energy"
    if not stage:
        return "wait"
    raise ValueError(f"Unsupported resume_stage: {stage}")


def _job_ids(workflow: dict[str, Any]) -> list[str]:
    values = workflow.get("active_slurm_jobs", [])
    if not isinstance(values, list):
        raise TypeError("active_slurm_jobs must be a list")

    identifiers = [str(value).strip() for value in values]
    if not identifiers:
        raise ValueError("Workflow has no active Slurm jobs")
    if any(not value.isdigit() for value in identifiers):
        raise ValueError(
            "Every persisted Slurm job ID must contain digits only"
        )
    return list(dict.fromkeys(identifiers))


def _submission_state(workflow: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow.get("adsorption_dft_jobs", [])
    preview = workflow.get("adsorption_dft_input_preview", {})
    if not isinstance(jobs, list) or not jobs:
        raise ValueError(
            "Workflow contains no finalized C12.5 adsorption jobs"
        )
    if not isinstance(preview, dict) or not preview.get("bundles"):
        raise ValueError(
            "Workflow contains no C12.5 adsorption preview"
        )

    context = workflow.get("task_context", {})
    if not isinstance(context, dict):
        context = {}
    return {
        **context,
        "task_id": str(workflow["task_id"]),
        "adsorption_dft_jobs": jobs,
        "adsorption_dft_input_preview": preview,
        "adsorption_dft_input_preparation": workflow.get(
            "adsorption_dft_input_preparation",
            {},
        ),
        "errors": [],
        "warnings": [],
        "status": "workflow_resume_created",
    }


def _adsorption_energy_state(
    workflow: dict[str, Any],
) -> dict[str, Any]:
    """Restore and validate the persisted inputs required by C12.7."""

    adsorption_results = workflow.get(
        "adsorption_parsed_results",
        [],
    )
    clean_slab_energies = workflow.get(
        "clean_slab_energies",
        {},
    )
    reference_energies = workflow.get(
        "reference_energies",
        {},
    )

    if (
        not isinstance(adsorption_results, list)
        or not adsorption_results
    ):
        raise ValueError(
            "Workflow contains no persisted adsorption results"
        )
    if (
        not isinstance(clean_slab_energies, dict)
        or not clean_slab_energies
    ):
        raise ValueError(
            "Workflow contains no persisted clean-slab energies"
        )
    if not isinstance(reference_energies, dict):
        raise TypeError(
            "reference_energies must be a dictionary"
        )

    required_slab_ids: set[str] = set()
    required_adsorbates: set[str] = set()
    for result in adsorption_results:
        if not isinstance(result, dict):
            raise TypeError(
                "Every persisted adsorption result must be a dictionary"
            )
        identity = result.get("scientific_identity", {})
        if not isinstance(identity, dict):
            raise TypeError(
                "Every adsorption result requires scientific_identity"
            )

        slab_id = str(
            identity.get("source_clean_slab_id", "")
        ).strip()
        adsorbate = str(
            identity.get("adsorbate", "")
        ).strip()
        if not slab_id:
            raise ValueError("source_clean_slab_id is missing")
        if not adsorbate:
            raise ValueError("adsorbate is missing")
        required_slab_ids.add(slab_id)
        required_adsorbates.add(adsorbate)

    missing_slab_ids = sorted(
        slab_id
        for slab_id in required_slab_ids
        if slab_id not in clean_slab_energies
    )
    missing_references = sorted(
        adsorbate
        for adsorbate in required_adsorbates
        if adsorbate not in reference_energies
    )
    if missing_slab_ids:
        raise ValueError(
            "Missing clean-slab energies: "
            + ", ".join(missing_slab_ids)
        )
    if missing_references:
        raise ValueError(
            "Missing reference energies: "
            + ", ".join(missing_references)
        )

    return {
        "task_id": str(workflow["task_id"]),
        "adsorption_parsed_results": adsorption_results,
        "clean_slab_energies": clean_slab_energies,
        "reference_energies": reference_energies,
        "adsorption_energy_input_preparation": workflow.get(
            "adsorption_energy_input_preparation",
            {},
        ),
        "errors": [],
        "status": "c12_7_resume_created",
    }


def _collect_decision(request: dict[str, Any]) -> dict[str, Any]:
    interrupt_type = str(request.get("type", ""))

    if interrupt_type == "result_download_review_required":
        return collect_download(request)
    if interrupt_type == "retry_plan_review_required":
        return collect_retry(request)
    if interrupt_type == "slab_review_required":
        return collect_slab_review_decision(request)
    if interrupt_type == "dft_input_review_required":
        return collect_dft_input_review_decision(request)
    if interrupt_type == "adsorption_structure_review_required":
        return collect_adsorption_structure_review(request)
    if interrupt_type == "adsorption_intermediate_review_required":
        return collect_adsorption_intermediate_review(request)
    if interrupt_type == "adsorption_dft_input_review_required":
        return collect_dft_input_review_decision({
            **request,
            "stage_label": "C12.5",
        })
    if interrupt_type == "adsorption_dft_execution_required":
        return collect_adsorption_dft_execution(request)
    if interrupt_type == "adsorption_energy_review_required":
        return collect_adsorption_energy_review(request)
    if interrupt_type == "remote_upload_review_required":
        return collect_remote_upload_review(request)
    if interrupt_type == "remote_submission_review_required":
        return collect_remote_submission_review(request)

    raise RuntimeError(
        f"Unsupported workflow-resume interrupt: {interrupt_type}"
    )


def _resume_interrupts(graph, result, config):
    while "__interrupt__" in result:
        interrupts = result.get("__interrupt__", ())
        if not interrupts:
            raise RuntimeError("LangGraph returned an empty interrupt")
        request = interrupts[0].value
        if not isinstance(request, dict):
            raise TypeError("LangGraph interrupt must be a dictionary")
        result = graph.invoke(
            Command(resume=_collect_decision(request)),
            config=config,
        )
    return result


def resume_workflow(
    workflow: dict[str, Any],
    thread_id: str,
) -> dict[str, Any]:
    target = resolve_resume_target(workflow)
    if target in {"complete", "wait"}:
        return {
            "status": (
                "workflow_already_complete"
                if target == "complete"
                else "workflow_waiting_without_resume_stage"
            ),
            "workflow_run": workflow,
        }

    config = {"configurable": {"thread_id": thread_id}}

    if target == "job_operations":
        graph = job_operations_graph
        initial_state = {
            "slurm_job_ids": _job_ids(workflow),
            "task_id": str(workflow["task_id"]),
            "errors": [],
            "warnings": [],
            "status": "workflow_resume_created",
        }
    elif target == "adsorption_submission":
        graph = adsorption_execution_graph
        initial_state = _submission_state(workflow)
    elif target == "adsorption_energy":
        graph = adsorption_energy_resume_graph
        initial_state = _adsorption_energy_state(workflow)
    else:
        graph = adsorption_job_operations_graph
        initial_state = {
            "requested_slurm_job_ids": _job_ids(workflow),
            "task_id": str(workflow["task_id"]),
            "errors": [],
            "status": "workflow_resume_created",
        }

    result = graph.invoke(initial_state, config=config)
    result = _resume_interrupts(graph, result, config)

    # C12.5 finalization persists all submission inputs. Continue into
    # C12.6 immediately while retaining its execution/upload/sbatch gates.
    if target == "job_operations":
        latest = WorkflowRunRepository().get(
            str(workflow["task_id"])
        )
        if (
            isinstance(latest, dict)
            and resolve_resume_target(latest)
            == "adsorption_submission"
        ):
            return resume_workflow(
                latest,
                f"{thread_id}-c12-6",
            )

    return result


def _thread_id(
    task_id: str,
    workflow: dict[str, Any],
    explicit: str,
) -> str:
    if explicit.strip():
        return explicit.strip()
    stage = str(workflow.get("resume_stage", "wait"))
    safe_stage = re.sub(r"[^A-Za-z0-9._-]+", "-", stage)
    return f"resume-{task_id}-{safe_stage}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Resume a persisted catalyst workflow by task_id"
        )
    )
    parser.add_argument("task_id")
    parser.add_argument(
        "--thread-id",
        default="",
        help="Optional stable LangGraph thread ID",
    )
    parser.add_argument(
        "--show-only",
        action="store_true",
        help="Display the persisted route without running a graph",
    )
    args = parser.parse_args()

    workflow = load_workflow(args.task_id)
    target = resolve_resume_target(workflow)
    show(
        "workflow_resume_plan",
        {
            "task_id": workflow.get("task_id"),
            "workflow_status": workflow.get("workflow_status"),
            "resume_stage": workflow.get("resume_stage"),
            "target": target,
            "active_slurm_jobs": workflow.get(
                "active_slurm_jobs",
                [],
            ),
            "terminal": workflow.get("terminal", False),
        },
    )

    if args.show_only:
        return

    result = resume_workflow(
        workflow,
        _thread_id(args.task_id, workflow, args.thread_id),
    )

    for key in (
        "monitor_result",
        "completion_result",
        "download_result",
        "parse_result",
        "clean_slab_result_readiness",
        "adsorption_reaction_plan",
        "adsorption_site_generation",
        "adsorbate_structure_generation",
        "adsorption_structure_quality",
        "adsorption_structure_review",
        "adsorption_dft_input_preparation",
        "dft_execution_options",
        "dft_local_preflight",
        "cluster_readonly_preflight",
        "remote_execution_plan",
        "remote_upload_result",
        "remote_submission_result",
        "submission_recording",
        "adsorption_result_ready",
        "adsorption_energy_input_preparation",
        "adsorption_energy_calculation",
        "adsorption_energy_review",
        "diagnosis_result",
        "workflow_run",
    ):
        if key in result:
            show(key, result[key])

    show("final", {"status": result.get("status")})


if __name__ == "__main__":
    main()
