from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.domain.failure_diagnosis import FailureDiagnosisService, RetryReviewGate
from app.domain.formation_energy_backfill import FormationEnergyBackfillService
from app.domain.result_download import ResultDownloadService
from app.domain.slurm_monitor import SlurmMonitorService
from app.domain.submitted_job_repository import SubmittedJobRepository
from app.domain.vasp_completion import VaspCompletionService
from app.domain.vasp_result_parser import VaspResultParser
from app.domain.workflow_run_repository import WorkflowRunRepository
from app.graph.checkpointing import persistent_checkpointer
from app.graph.nodes import (
    adsorbate_structure_generation_node,
    adsorption_dft_finalize_node,
    adsorption_dft_preview_node,
    adsorption_dft_review_node,
    adsorption_dft_revision_apply_node,
    adsorption_dft_revision_plan_node,
    adsorption_reaction_planning_node,
    adsorption_site_generation_node,
    adsorption_structure_quality_node,
    adsorption_structure_review_node,
    dft_input_finalize_node,
    dft_input_preview_node,
    dft_input_review_node,
    dft_revision_apply_node,
    dft_revision_plan_node,
    slab_generation_node,
    slab_quality_node,
    slab_review_node,
)
from app.graph.routes import (
    route_after_adsorption_dft_review,
)


class JobOperationState(TypedDict, total=False):
    slurm_job_ids: list[str]
    task_analysis: dict[str, Any]
    reaction_profile: dict[str, Any]
    papers: list[dict[str, Any]]
    adsorption_user_overrides: dict[str, Any]
    adsorption_literature_suggestions: list[str]
    clean_slab_result_readiness: dict[str, Any]
    monitor_result: dict[str, Any]
    completion_result: dict[str, Any]
    download_review: dict[str, Any]
    download_result: dict[str, Any]
    parse_result: dict[str, Any]
    diagnosis_result: dict[str, Any]
    formation_energy_backfill: dict[str, Any]
    async_stability_screening: dict[str, Any]
    slab_eligible_structures: list[dict[str, Any]]
    slab_generation: dict[str, Any]
    generated_slabs: list[dict[str, Any]]
    slab_quality: dict[str, Any]
    quality_passed_slabs: list[dict[str, Any]]
    slab_review: dict[str, Any]
    dft_approved_slabs: list[dict[str, Any]]
    dft_input_preview: dict[str, Any]
    dft_input_review: dict[str, Any]
    dft_revision_request: dict[str, str]
    dft_revision_plan: dict[str, Any]
    dft_revision_validation: dict[str, Any]
    dft_revision_history: list[dict[str, Any]]
    dft_revision_count: int
    dft_input_preparation: dict[str, Any]
    dft_jobs: list[dict[str, Any]]
    adsorption_source_slabs: list[dict[str, Any]]
    adsorption_reaction_plan: dict[str, Any]
    adsorption_intermediate_review: dict[str, Any]
    selected_adsorbate: str
    reference_energy_definition: dict[str, Any]
    planned_adsorbates: list[str]
    adsorption_site_generation: dict[str, Any]
    adsorption_sites: list[dict[str, Any]]
    adsorbate_structure_generation: dict[str, Any]
    adsorption_structures: list[dict[str, Any]]
    adsorption_structure_quality: dict[str, Any]
    quality_passed_adsorption_structures: list[dict[str, Any]]
    adsorption_structure_review: dict[str, Any]
    adsorption_dft_approved_structures: list[dict[str, Any]]
    adsorption_dft_input_preview: dict[str, Any]
    adsorption_dft_input_review: dict[str, Any]
    adsorption_dft_revision_request: dict[str, str]
    adsorption_dft_revision_plan: dict[str, Any]
    adsorption_dft_revision_validation: dict[str, Any]
    adsorption_dft_revision_history: list[dict[str, Any]]
    adsorption_dft_revision_count: int
    adsorption_dft_input_preparation: dict[str, Any]
    adsorption_dft_jobs: list[dict[str, Any]]
    workflow_run: dict[str, Any]
    task_id: str
    resume_status: str
    retry_reviews: list[dict[str, Any]]
    status: str
    errors: list[dict[str, Any]]
    warnings: list[str]


@dataclass
class JobOperationServices:
    repository: SubmittedJobRepository
    monitor: SlurmMonitorService
    completion: VaspCompletionService
    downloader: ResultDownloadService
    parser: VaspResultParser
    diagnosis: FailureDiagnosisService


def create_job_operation_services() -> JobOperationServices:
    repository = SubmittedJobRepository()
    return JobOperationServices(
        repository=repository,
        monitor=SlurmMonitorService(repository=repository),
        completion=VaspCompletionService(repository=repository),
        downloader=ResultDownloadService(repository=repository),
        parser=VaspResultParser(repository=repository),
        diagnosis=FailureDiagnosisService(repository=repository),
    )


services = create_job_operation_services()


def monitor_node(state: JobOperationState) -> dict[str, Any]:
    result = services.monitor.poll(state.get("slurm_job_ids"))
    return {"monitor_result": result, "status": result["status"]}


def completion_node(state: JobOperationState) -> dict[str, Any]:
    result = services.completion.inspect(state.get("slurm_job_ids"))
    return {"completion_result": result, "status": result["status"]}


def download_review_node(state: JobOperationState) -> dict[str, Any]:
    jobs = [
        job for job in state.get("completion_result", {}).get("jobs", [])
        if job.get("download_eligible")
    ]
    if not jobs:
        return {
            "download_review": {
                "status": "result_download_review_skipped",
                "approved_slurm_job_ids": [],
            },
            "status": "result_download_review_skipped",
        }
    ids = [str(job["slurm_job_id"]) for job in jobs]
    decision = interrupt({
        "type": "result_download_review_required",
        "jobs": [{
            "slurm_job_id": job.get("slurm_job_id"),
            "job_id": job.get("job_id"),
            "scheduler_state": job.get("scheduler_state"),
            "vasp_decision": job.get("vasp_decision"),
            "remote_job_directory": job.get("remote_job_directory"),
        } for job in jobs],
        "confirmation_phrase": "DOWNLOAD " + ",".join(ids),
    })
    if not isinstance(decision, dict):
        raise TypeError("Download decision must be a dictionary")
    approved = decision.get("approved_slurm_job_ids", [])
    status = (
        "result_download_approved"
        if decision.get("action") == "approve_download" and approved
        else "result_download_deferred"
    )
    review = {**decision, "status": status}
    return {"download_review": review, "status": status}


def download_node(state: JobOperationState) -> dict[str, Any]:
    result = services.downloader.download(state.get("download_review", {}))
    return {"download_result": result, "status": result["status"]}


def parse_node(state: JobOperationState) -> dict[str, Any]:
    ids = [
        str(job["slurm_job_id"])
        for job in state.get("download_result", {}).get("jobs", [])
    ]
    result = services.parser.parse(ids)
    return {"parse_result": result, "status": result["status"]}


def clean_slab_result_ready_node(
    state: JobOperationState,
) -> dict[str, Any]:
    """Adapt converged C10 clean-slab results for C12.1-C12.2."""

    records = state.get(
        "parse_result",
        {},
    ).get("jobs", [])
    if not isinstance(records, list):
        records = []

    clean_slab_records = [
        record
        for record in records
        if (
            isinstance(record, dict)
            and record.get("job_source") == "c10_slab"
        )
    ]
    ready: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for record in clean_slab_records:
        try:
            if (
                record.get("vasp_decision")
                != "completed_converged"
            ):
                raise ValueError(
                    "Clean-slab DFT is not completed and converged"
                )

            if record.get("result_parsing_status") != "parsed":
                raise ValueError(
                    "Clean-slab result has not been parsed"
                )

            identity = record.get("scientific_identity")
            if not isinstance(identity, dict):
                raise ValueError(
                    "Clean-slab scientific_identity is required"
                )

            if (
                identity.get("calculation_type")
                != "clean_slab_relax"
            ):
                raise ValueError(
                    "Unsupported clean-slab calculation_type"
                )

            slab_id = str(
                identity.get("slab_id", "")
            ).strip()
            candidate_id = str(
                identity.get("candidate_id", "")
            ).strip()
            slurm_job_id = str(
                record.get("slurm_job_id", "")
            ).strip()

            if not slab_id or not candidate_id:
                raise ValueError(
                    "Clean-slab slab_id and candidate_id are required"
                )
            if not slurm_job_id.isdigit():
                raise ValueError(
                    "Clean-slab Slurm job ID must be numeric"
                )

            parsed = record.get("parsed_vasp_result")
            if not isinstance(parsed, dict):
                raise ValueError(
                    "parsed_vasp_result is required"
                )

            final_energy = parsed.get("final_toten_ev")
            if (
                not isinstance(final_energy, (int, float))
                or isinstance(final_energy, bool)
            ):
                raise ValueError(
                    "Parsed clean slab has no numeric final TOTEN"
                )

            final_structure = parsed.get("final_structure")
            if not isinstance(final_structure, dict):
                raise ValueError(
                    "Parsed clean slab has no final structure"
                )

            contcar_path = str(
                final_structure.get("path", "")
            ).strip()
            if not contcar_path:
                raise ValueError(
                    "Parsed clean slab has no CONTCAR path"
                )
            contcar = Path(contcar_path).resolve()
            if contcar.name.upper() != "CONTCAR":
                raise ValueError(
                    "Parsed clean-slab structure must be CONTCAR"
                )
            if not contcar.is_file():
                raise FileNotFoundError(
                    f"Parsed clean-slab CONTCAR does not exist: {contcar}"
                )

            atom_count = final_structure.get("atom_count")
            if atom_count != 48:
                raise ValueError(
                    "C12 clean slab must contain exactly 48 atoms"
                )
            if atom_count != identity.get("atom_count"):
                raise ValueError(
                    "Parsed atom_count differs from submitted identity"
                )

            elements = final_structure.get("elements")
            counts = final_structure.get("counts")
            if (
                not isinstance(elements, list)
                or not isinstance(counts, list)
                or len(elements) != len(counts)
                or dict(zip(elements, counts))
                != identity.get("composition")
            ):
                raise ValueError(
                    "Parsed composition differs from submitted identity"
                )

            ready.append({
                "slab_id": slab_id,
                "candidate_id": candidate_id,
                "clean_slab_slurm_job_id": slurm_job_id,
                "clean_slab_dft_status": (
                    "completed_converged"
                ),
                "clean_slab_result_parsing_status": "parsed",
                "relaxed_contcar_path": str(contcar),
                "clean_slab_energy_ev": float(final_energy),
                "clean_slab_energy_source": {
                    "calculation_type": "clean_slab_relax",
                    "slurm_job_id": slurm_job_id,
                    "parsed_field": "final_toten_ev",
                    "energy_unit": "eV",
                    "data_version": "c12-clean-slab-energy-v1",
                },
                "approved_for_adsorption": True,
                "structure_source": (
                    "relaxed_clean_slab_contcar"
                ),
                "parsed_final_structure": final_structure,
                "submitted_scientific_identity": identity,
            })

        except Exception as error:
            errors.append({
                "slurm_job_id": record.get("slurm_job_id"),
                "job_id": record.get("job_id"),
                "error_type": type(error).__name__,
                "message": str(error),
            })

    if ready and not errors:
        status = "clean_slabs_ready_for_adsorption"
    elif ready:
        status = "clean_slabs_partially_ready"
    else:
        status = "clean_slabs_not_ready"

    task_ids = {
        str(record.get("task_id", "")).strip()
        for record in clean_slab_records
        if str(record.get("task_id", "")).strip()
    }
    task_id = str(state.get("task_id", "")).strip()
    if not task_id and len(task_ids) == 1:
        task_id = next(iter(task_ids))

    persisted_workflow = (
        WorkflowRunRepository().get(task_id)
        if task_id
        else None
    ) or {}
    task_context = persisted_workflow.get(
        "task_context",
        {},
    )
    if not isinstance(task_context, dict):
        task_context = {}

    workflow = {}
    if task_id and ready:
        workflow = WorkflowRunRepository().update(
            task_id,
            {
                "workflow_status": (
                    "ready_for_adsorption_modeling"
                ),
                "active_slurm_jobs": [
                    item["clean_slab_slurm_job_id"]
                    for item in ready
                ],
                "resume_stage": (
                    "c12.1_adsorption_planning"
                ),
                "last_completed_stage": (
                    "clean_slab_result_parsing"
                ),
                "adsorption_source_slabs": ready,
                "clean_slab_energies": {
                    item["slab_id"]: item["clean_slab_energy_ev"]
                    for item in ready
                },
                "clean_slab_energy_sources": {
                    item["slab_id"]: item["clean_slab_energy_source"]
                    for item in ready
                },
                "terminal": False,
            },
        )

    return {
        "task_id": task_id,
        "task_analysis": task_context.get(
            "task_analysis",
            state.get("task_analysis", {}),
        ),
        "reaction_profile": task_context.get(
            "reaction_profile",
            state.get("reaction_profile", {}),
        ),
        "papers": task_context.get(
            "papers",
            state.get("papers", []),
        ),
        "adsorption_user_overrides": task_context.get(
            "adsorption_user_overrides",
            state.get("adsorption_user_overrides", {}),
        ),
        "adsorption_literature_suggestions": task_context.get(
            "adsorption_literature_suggestions",
            state.get("adsorption_literature_suggestions", []),
        ),
        "adsorption_source_slabs": ready,
        "clean_slab_result_readiness": {
            "schema_version": "c12-main-bridge-v1",
            "stage": "clean_slab_result_adaptation",
            "status": status,
            "input_count": len(clean_slab_records),
            "ready_count": len(ready),
            "failed_count": len(errors),
            "slabs": ready,
            "errors": errors,
            "next_stage": (
                "c12.1_adsorption_planning"
                if ready
                else "clean_slab_result_diagnosis"
            ),
        },
        "workflow_run": workflow,
        "status": status,
    }


def adsorption_intermediate_review_node(
    state: JobOperationState,
) -> dict[str, Any]:
    """Require one and only one adsorbate before C12.2."""

    plan = state.get("adsorption_reaction_plan", {})
    candidates = plan.get("candidate_adsorbates", [])
    if not isinstance(candidates, list):
        candidates = []
    candidates = list(dict.fromkeys(
        str(value).strip() for value in candidates if str(value).strip()
    ))
    if not candidates:
        return {
            "adsorption_intermediate_review": {
                "status": "adsorption_intermediate_selection_unavailable",
                "selected_adsorbate": None,
            },
            "planned_adsorbates": [],
            "status": "adsorption_intermediate_selection_unavailable",
        }

    decision = interrupt({
        "type": "adsorption_intermediate_review_required",
        "message": (
            "Select exactly one intermediate for this task. "
            "Use a separate task for another intermediate."
        ),
        "candidate_adsorbates": candidates,
        "selection_limit": 1,
        "coadsorption_allowed": False,
        "reference_energy_definitions": plan.get(
            "reference_energy_definitions", {}
        ),
    })
    if not isinstance(decision, dict):
        raise TypeError("Adsorption-intermediate decision must be an object")
    selected = str(decision.get("selected_adsorbate", "")).strip()
    if selected not in candidates:
        raise ValueError("Select exactly one listed adsorption intermediate")

    definitions = plan.get("reference_energy_definitions", {})
    definition = definitions.get(selected, {}) if isinstance(definitions, dict) else {}
    selected_plan = {
        **plan,
        "status": "adsorption_reaction_plan_ready",
        "formal_adsorbates": [selected],
        "selected_adsorbate": selected,
        "selected_adsorbate_count": 1,
        "reference_energy_definition": definition,
        "ready_for_site_generation": True,
        "reason": "One adsorption intermediate was approved by the user.",
        "next_stage": "c12.2_adsorption_site_generation",
    }
    review = {
        "schema_version": "c12.1-single-intermediate-v1",
        "stage": "c12.1_single_intermediate_review",
        "status": "adsorption_intermediate_selected",
        "selected_adsorbate": selected,
        "selection_count": 1,
        "note": str(decision.get("note", "")).strip(),
    }

    task_id = str(state.get("task_id", "")).strip()
    if task_id:
        repository = WorkflowRunRepository()
        current = repository.get(task_id) or {}
        context = current.get("task_context", {})
        if not isinstance(context, dict):
            context = {}
        repository.update(task_id, {
            "workflow_status": "adsorption_intermediate_selected",
            "resume_stage": "c12.2_adsorption_site_generation",
            "last_completed_stage": "c12.1_single_intermediate_review",
            "selected_adsorbate": selected,
            "reference_energy_definition": definition,
            "adsorption_reaction_plan": selected_plan,
            "task_context": {
                **context,
                "selected_adsorbate": selected,
                "adsorption_reaction_plan": selected_plan,
            },
            "terminal": False,
        })

    return {
        "adsorption_reaction_plan": selected_plan,
        "adsorption_intermediate_review": review,
        "selected_adsorbate": selected,
        "reference_energy_definition": definition,
        "planned_adsorbates": [selected],
        "status": review["status"],
    }


def async_adsorption_dft_finalize_node(
    state: JobOperationState,
) -> dict[str, Any]:
    """Finalize C12.5 and persist the C12.6 submission handoff."""

    result = adsorption_dft_finalize_node(state)
    jobs = result.get("adsorption_dft_jobs", [])
    if not isinstance(jobs, list):
        jobs = []

    task_id = str(state.get("task_id", "")).strip()
    workflow = {}
    if task_id and jobs:
        workflow = WorkflowRunRepository().update(
            task_id,
            {
                "workflow_status": (
                    "adsorption_dft_inputs_ready"
                ),
                "resume_stage": (
                    "c12.6_adsorption_submission"
                ),
                "last_completed_stage": (
                    "c12.5_adsorption_dft_finalize"
                ),
                "adsorption_dft_jobs": jobs,
                "adsorption_dft_input_preview": state.get(
                    "adsorption_dft_input_preview",
                    {},
                ),
                "adsorption_dft_input_preparation": result.get(
                    "adsorption_dft_input_preparation",
                    {},
                ),
                "terminal": False,
            },
        )

    return {
        **result,
        "workflow_run": workflow,
        "resume_status": (
            "ready_for_c12_6_submission"
            if jobs
            else "c12_5_not_ready"
        ),
    }


def diagnosis_node(state: JobOperationState) -> dict[str, Any]:
    result = services.diagnosis.diagnose(state.get("slurm_job_ids"))
    return {"diagnosis_result": result, "status": result["status"]}


def formation_energy_backfill_node(state: JobOperationState) -> dict[str, Any]:
    """Automatically run C11.7/C7 for parsed, converged C6D jobs."""
    results, errors = [], []
    repository = services.repository
    service = FormationEnergyBackfillService(repository=repository)
    ids = [
        str(job.get("slurm_job_id"))
        for job in state.get("parse_result", {}).get("jobs", [])
        if job.get("job_source") == "c6d_bulk_formation"
    ]
    for slurm_job_id in ids:
        try:
            results.append(service.calculate_from_record(slurm_job_id))
        except Exception as error:
            errors.append({
                "slurm_job_id": slurm_job_id,
                "error_type": type(error).__name__,
                "message": str(error),
            })

    eligible = [
        result["backfilled_structure"] for result in results
        if result.get("eligible_for_slab")
    ]
    failed = [
        result for result in results if not result.get("eligible_for_slab")
    ]
    status = (
        "ready_for_c8_resume" if eligible else
        "completed_screened_out" if results and not errors else
        "formation_energy_backfill_failed" if errors else
        "formation_energy_backfill_skipped"
    )
    task_ids = {
        str(result.get("task_id")) for result in results if result.get("task_id")
    }
    workflow = {}
    if len(task_ids) == 1:
        task_id = next(iter(task_ids))
        workflow = WorkflowRunRepository().update(task_id, {
            "workflow_status": status,
            "active_slurm_jobs": ids,
            "resume_stage": "slab_generation" if eligible else None,
            "last_completed_stage": "c7_stability_screening",
            "terminal": bool(failed and not eligible and not errors),
        })
    return {
        "task_id": next(iter(task_ids)) if len(task_ids) == 1 else state.get("task_id", ""),
        "formation_energy_backfill": {
            "schema_version": "c11.9",
            "status": status,
            "completed_count": len(results),
            "screened_out_count": len(failed),
            "eligible_count": len(eligible),
            "results": results,
            "errors": errors,
        },
        "async_stability_screening": {
            "status": status,
            "eligible_count": len(eligible),
            "screened_out_count": len(failed),
        },
        "slab_eligible_structures": eligible,
        "workflow_run": workflow,
        "resume_status": status,
        "status": status,
    }


def async_slab_generation_node(state: JobOperationState) -> dict[str, Any]:
    result = slab_generation_node(state)
    _update_resume_workflow(state, "c8_slab_generation", result.get("status", ""))
    return result


def async_slab_quality_node(state: JobOperationState) -> dict[str, Any]:
    result = slab_quality_node(state)
    _update_resume_workflow(state, "c9_slab_quality", result.get("status", ""))
    return result


def async_slab_review_node(state: JobOperationState) -> dict[str, Any]:
    result = slab_review_node(state)
    _update_resume_workflow(state, "c9_slab_review", result.get("status", ""))
    return result


def async_dft_preview_node(state: JobOperationState) -> dict[str, Any]:
    result = dft_input_preview_node(state)
    _update_resume_workflow(state, "c10_dft_preview", result.get("status", ""))
    return result


def async_dft_review_node(state: JobOperationState) -> dict[str, Any]:
    result = dft_input_review_node(state)
    _update_resume_workflow(state, "c10_dft_review", result.get("status", ""))
    return result


def async_dft_revision_plan_node(state: JobOperationState) -> dict[str, Any]:
    return dft_revision_plan_node(state)


def async_dft_revision_apply_node(state: JobOperationState) -> dict[str, Any]:
    return dft_revision_apply_node(state)


def async_dft_finalize_node(state: JobOperationState) -> dict[str, Any]:
    result = dft_input_finalize_node(state)
    _update_resume_workflow(
        state, "c10_dft_finalize", "c11_9_continuation_completed", terminal=True
    )
    return {**result, "resume_status": "c11_9_continuation_completed"}


def _update_resume_workflow(
    state: JobOperationState, stage: str, status: str, terminal: bool = False
) -> None:
    task_id = str(state.get("task_id", ""))
    if task_id:
        WorkflowRunRepository().update(task_id, {
            "workflow_status": status,
            "last_completed_stage": stage,
            "resume_stage": None if terminal else stage,
            "terminal": terminal,
        })


def retry_review_node(state: JobOperationState) -> dict[str, Any]:
    jobs = [
        job for job in state.get("diagnosis_result", {}).get("jobs", [])
        if job.get("retry_plan", {}).get("eligible")
    ]
    if not jobs:
        return {"retry_reviews": [], "status": "retry_review_skipped"}
    request = {
        "type": "retry_plan_review_required",
        "jobs": [{
            "slurm_job_id": job.get("slurm_job_id"),
            "job_id": job.get("job_id"),
            "diagnosis": job.get("failure_diagnosis"),
            "retry_plan": job.get("retry_plan"),
        } for job in jobs],
    }
    decisions = interrupt(request)
    if not isinstance(decisions, dict):
        raise TypeError("Retry decisions must be a dictionary")
    by_id = decisions.get("decisions", {})
    reviews = []
    for job in jobs:
        job_id = str(job["slurm_job_id"])
        review = RetryReviewGate.review(job, by_id.get(job_id, {"action": "defer"}))
        services.repository.update(job_id, {"retry_review": review})
        reviews.append(review)
    return {"retry_reviews": reviews, "status": "retry_reviews_recorded"}


def route_after_download_review(state: JobOperationState) -> Literal["download", "diagnose"]:
    return "download" if state.get("download_review", {}).get("status") == "result_download_approved" else "diagnose"


def route_after_download(
    state: JobOperationState,
) -> Literal["parse", "end"]:
    """Parse only jobs that were downloaded in the current run."""

    jobs = state.get("download_result", {}).get("jobs", [])
    return "parse" if isinstance(jobs, list) and jobs else "end"


def route_after_parse(
    state: JobOperationState,
) -> Literal[
    "bulk_backfill",
    "clean_slab_adsorption",
    "diagnose",
]:
    """Separate bulk formation and clean-slab result lifecycles."""

    jobs = state.get("parse_result", {}).get("jobs", [])
    if not isinstance(jobs, list):
        jobs = []

    sources = {
        str(job.get("job_source", ""))
        for job in jobs
        if isinstance(job, dict)
    }

    supported_sources = sources & {
        "c6d_bulk_formation",
        "c10_slab",
    }

    if supported_sources == {"c6d_bulk_formation"}:
        return "bulk_backfill"
    if supported_sources == {"c10_slab"}:
        return "clean_slab_adsorption"
    return "diagnose"


def route_after_clean_slab_result(
    state: JobOperationState,
) -> Literal["adsorption", "diagnose"]:
    return (
        "adsorption"
        if state.get("adsorption_source_slabs")
        else "diagnose"
    )


def route_after_diagnosis(state: JobOperationState) -> Literal["retry_review", "end"]:
    return "retry_review" if state.get("diagnosis_result", {}).get("retry_candidate_count", 0) else "end"


def route_after_backfill(
    state: JobOperationState,
) -> Literal["continue", "diagnose", "end"]:
    status = state.get("resume_status")
    if status == "ready_for_c8_resume":
        return "continue"
    if status in {"formation_energy_backfill_failed", "formation_energy_backfill_skipped"}:
        return "diagnose"
    return "end"


def route_after_async_dft_review(
    state: JobOperationState,
) -> Literal["revise", "finalize"]:
    return (
        "revise"
        if state.get("dft_input_review", {}).get("action") == "revise"
        else "finalize"
    )


def build_job_operations_graph(checkpointer=None):
    builder = StateGraph(JobOperationState)
    for name, node in (
        ("monitor", monitor_node),
        ("completion", completion_node),
        ("download_review", download_review_node),
        ("download", download_node),
        ("parse", parse_node),
        ("clean_slab_result_ready", clean_slab_result_ready_node),
        ("formation_energy_backfill", formation_energy_backfill_node),
        ("async_slab_generation", async_slab_generation_node),
        ("async_slab_quality", async_slab_quality_node),
        ("async_slab_review", async_slab_review_node),
        ("async_dft_preview", async_dft_preview_node),
        ("async_dft_review", async_dft_review_node),
        ("async_dft_revision_plan", async_dft_revision_plan_node),
        ("async_dft_revision_apply", async_dft_revision_apply_node),
        ("async_dft_finalize", async_dft_finalize_node),
        (
            "adsorption_reaction_planning",
            adsorption_reaction_planning_node,
        ),
        (
            "adsorption_intermediate_review",
            adsorption_intermediate_review_node,
        ),
        (
            "adsorption_site_generation",
            adsorption_site_generation_node,
        ),
        (
            "adsorbate_structure_generation",
            adsorbate_structure_generation_node,
        ),
        (
            "adsorption_structure_quality",
            adsorption_structure_quality_node,
        ),
        (
            "adsorption_structure_review",
            adsorption_structure_review_node,
        ),
        (
            "adsorption_dft_preview",
            adsorption_dft_preview_node,
        ),
        (
            "adsorption_dft_review",
            adsorption_dft_review_node,
        ),
        (
            "adsorption_dft_revision_plan",
            adsorption_dft_revision_plan_node,
        ),
        (
            "adsorption_dft_revision_apply",
            adsorption_dft_revision_apply_node,
        ),
        (
            "adsorption_dft_finalize",
            async_adsorption_dft_finalize_node,
        ),
        ("diagnosis", diagnosis_node),
        ("retry_review", retry_review_node),
    ):
        builder.add_node(name, node)
    builder.add_edge(START, "monitor")
    builder.add_edge("monitor", "completion")
    builder.add_edge("completion", "download_review")
    builder.add_conditional_edges(
        "download_review", route_after_download_review,
        {"download": "download", "diagnose": "diagnosis"},
    )
    builder.add_conditional_edges(
        "download",
        route_after_download,
        {"parse": "parse", "end": END},
    )
    builder.add_conditional_edges(
        "parse",
        route_after_parse,
        {
            "bulk_backfill": "formation_energy_backfill",
            "clean_slab_adsorption": "clean_slab_result_ready",
            "diagnose": "diagnosis",
        },
    )
    builder.add_conditional_edges(
        "clean_slab_result_ready",
        route_after_clean_slab_result,
        {
            "adsorption": "adsorption_reaction_planning",
            "diagnose": "diagnosis",
        },
    )
    builder.add_conditional_edges(
        "formation_energy_backfill", route_after_backfill,
        {
            "continue": "async_slab_generation",
            "diagnose": "diagnosis",
            "end": END,
        },
    )
    builder.add_edge("async_slab_generation", "async_slab_quality")
    builder.add_edge("async_slab_quality", "async_slab_review")
    builder.add_edge("async_slab_review", "async_dft_preview")
    builder.add_edge("async_dft_preview", "async_dft_review")
    builder.add_conditional_edges(
        "async_dft_review", route_after_async_dft_review,
        {
            "revise": "async_dft_revision_plan",
            "finalize": "async_dft_finalize",
        },
    )
    builder.add_edge("async_dft_revision_plan", "async_dft_revision_apply")
    builder.add_edge("async_dft_revision_apply", "async_dft_review")
    builder.add_edge("async_dft_finalize", END)
    builder.add_edge(
        "adsorption_reaction_planning",
        "adsorption_intermediate_review",
    )
    builder.add_edge(
        "adsorption_intermediate_review",
        "adsorption_site_generation",
    )
    builder.add_edge(
        "adsorption_site_generation",
        "adsorbate_structure_generation",
    )
    builder.add_edge(
        "adsorbate_structure_generation",
        "adsorption_structure_quality",
    )
    builder.add_edge(
        "adsorption_structure_quality",
        "adsorption_structure_review",
    )
    builder.add_edge(
        "adsorption_structure_review",
        "adsorption_dft_preview",
    )
    builder.add_edge(
        "adsorption_dft_preview",
        "adsorption_dft_review",
    )
    builder.add_conditional_edges(
        "adsorption_dft_review",
        route_after_adsorption_dft_review,
        {
            "revise": "adsorption_dft_revision_plan",
            "finalize": "adsorption_dft_finalize",
        },
    )
    builder.add_edge(
        "adsorption_dft_revision_plan",
        "adsorption_dft_revision_apply",
    )
    builder.add_edge(
        "adsorption_dft_revision_apply",
        "adsorption_dft_review",
    )
    builder.add_edge("adsorption_dft_finalize", END)
    builder.add_conditional_edges(
        "diagnosis", route_after_diagnosis,
        {"retry_review": "retry_review", "end": END},
    )
    builder.add_edge("retry_review", END)
    return builder.compile(checkpointer=checkpointer or persistent_checkpointer())


job_operations_graph = build_job_operations_graph()
