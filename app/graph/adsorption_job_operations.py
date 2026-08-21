from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.domain.workflow_run_repository import (
    WorkflowRunRepository,
)
from app.domain.adsorption_reference_energy import (
    AdsorptionReferenceEnergyCatalog,
)
from app.graph.nodes import (
    adsorption_energy_calculation_node,
    adsorption_energy_review_node,
)
from app.graph.job_operations import (
    diagnosis_node,
    download_node,
    download_review_node,
    parse_node,
    retry_review_node,
    services,
)


reference_energy_catalog = AdsorptionReferenceEnergyCatalog()


class AdsorptionJobOperationState(TypedDict, total=False):
    requested_slurm_job_ids: list[str]
    slurm_job_ids: list[str]
    task_id: str
    source_filter: dict[str, Any]
    monitor_result: dict[str, Any]
    completion_result: dict[str, Any]
    download_review: dict[str, Any]
    download_result: dict[str, Any]
    parse_result: dict[str, Any]
    adsorption_result_ready: dict[str, Any]
    adsorption_parsed_results: list[dict[str, Any]]
    adsorption_energy_input_preparation: dict[str, Any]
    clean_slab_energies: dict[str, Any]
    reference_energies: dict[str, Any]
    adsorption_energy_calculation: dict[str, Any]
    adsorption_energy_drafts: list[dict[str, Any]]
    adsorption_energy_review: dict[str, Any]
    approved_adsorption_energies: list[dict[str, Any]]
    diagnosis_result: dict[str, Any]
    retry_reviews: list[dict[str, Any]]
    workflow_run: dict[str, Any]
    status: str
    errors: list[dict[str, Any]]


def adsorption_source_filter_node(
    state: AdsorptionJobOperationState,
) -> dict[str, Any]:
    """Select only persisted C12.5 adsorption jobs."""

    requested = {
        str(value)
        for value in state.get(
            "requested_slurm_job_ids",
            state.get("slurm_job_ids", []),
        )
    }
    records = services.repository.list_records()
    adsorption_records = [
        record
        for record in records
        if (
            record.get("job_source")
            == "c12_5_adsorption"
            and (
                not requested
                or str(record.get("slurm_job_id"))
                in requested
            )
        )
    ]
    identifiers = [
        str(record["slurm_job_id"])
        for record in adsorption_records
    ]
    task_ids = {
        str(record.get("task_id", ""))
        for record in adsorption_records
        if record.get("task_id")
    }

    return {
        "slurm_job_ids": identifiers,
        "task_id": (
            next(iter(task_ids))
            if len(task_ids) == 1
            else str(state.get("task_id", ""))
        ),
        "source_filter": {
            "schema_version": "c12.6",
            "status": (
                "adsorption_jobs_selected"
                if identifiers
                else "adsorption_jobs_empty"
            ),
            "job_source": "c12_5_adsorption",
            "requested_count": len(requested),
            "selected_count": len(identifiers),
            "slurm_job_ids": identifiers,
        },
        "status": (
            "adsorption_jobs_selected"
            if identifiers
            else "adsorption_jobs_empty"
        ),
    }


def adsorption_monitor_node(
    state: AdsorptionJobOperationState,
) -> dict[str, Any]:
    result = services.monitor.poll(
        state.get("slurm_job_ids", [])
    )
    return {
        "monitor_result": result,
        "status": result["status"],
    }


def adsorption_completion_node(
    state: AdsorptionJobOperationState,
) -> dict[str, Any]:
    result = services.completion.inspect(
        state.get("slurm_job_ids", [])
    )
    return {
        "completion_result": result,
        "status": result["status"],
    }


def adsorption_result_ready_node(
    state: AdsorptionJobOperationState,
) -> dict[str, Any]:
    """Expose converged parsed adsorption energies to C12.7."""

    jobs = state.get("parse_result", {}).get("jobs", [])
    if not isinstance(jobs, list):
        jobs = []

    ready = [
        job
        for job in jobs
        if (
            job.get("job_source") == "c12_5_adsorption"
            and job.get("vasp_decision")
            == "completed_converged"
            and job.get("result_parsing_status") == "parsed"
            and job.get("parsed_vasp_result", {}).get(
                "final_toten_ev"
            ) is not None
        )
    ]
    status = (
        "adsorption_results_ready"
        if ready
        else "adsorption_results_not_ready"
    )
    task_ids = {
        str(job.get("task_id", ""))
        for job in jobs
        if job.get("task_id")
    }
    task_id = (
        next(iter(task_ids))
        if len(task_ids) == 1
        else str(state.get("task_id", ""))
    )
    workflow = {}
    if task_id:
        workflow = WorkflowRunRepository().update(
            task_id,
            {
                "workflow_status": status,
                "active_slurm_jobs": state.get(
                    "slurm_job_ids",
                    [],
                ),
                "resume_stage": (
                    "c12.7_adsorption_energy"
                    if ready
                    else "c12.6_adsorption_result_monitoring"
                ),
                "last_completed_stage": (
                    "c12.6_adsorption_result_parsing"
                ),
                "terminal": False,
            },
        )

    result = {
        "schema_version": "c12.6",
        "stage": "adsorption_result_readiness",
        "status": status,
        "parsed_count": len(jobs),
        "ready_count": len(ready),
        "results": ready,
        "formation_energy_backfill_performed": False,
        "automatic_retry_performed": False,
        "next_stage": "c12.7_adsorption_energy",
    }
    return {
        "task_id": task_id,
        "adsorption_result_ready": result,
        "adsorption_parsed_results": ready,
        "workflow_run": workflow,
        "status": status,
    }


def adsorption_energy_input_node(
    state: AdsorptionJobOperationState,
) -> dict[str, Any]:
    """Prepare parsed adsorption, clean-slab, and reference energies."""

    task_id = str(state.get("task_id", "")).strip()
    adsorption_results = state.get(
        "adsorption_parsed_results",
        [],
    )
    if not isinstance(adsorption_results, list):
        adsorption_results = []

    workflow = (
        WorkflowRunRepository().get(task_id)
        if task_id
        else None
    ) or {}
    persisted_references = workflow.get(
        "reference_energies",
        {},
    )
    reference_energies: dict[str, Any] = (
        dict(persisted_references)
        if isinstance(persisted_references, dict)
        else {}
    )

    clean_records = [
        record
        for record in services.repository.list_records()
        if (
            record.get("job_source") == "c10_slab"
            and str(record.get("task_id", "")) == task_id
            and record.get("vasp_decision")
            == "completed_converged"
            and record.get("result_parsing_status") == "parsed"
        )
    ]

    persisted_clean = workflow.get("clean_slab_energies", {})
    clean_slab_energies: dict[str, Any] = (
        dict(persisted_clean)
        if isinstance(persisted_clean, dict)
        else {}
    )
    for record in clean_records:
        identity = record.get("scientific_identity", {})
        parsed = record.get("parsed_vasp_result", {})
        if not isinstance(identity, dict) or not isinstance(parsed, dict):
            continue
        slab_id = str(identity.get("slab_id", "")).strip()
        energy = parsed.get("final_toten_ev")
        if (
            slab_id
            and isinstance(energy, (int, float))
            and not isinstance(energy, bool)
        ):
            clean_slab_energies[slab_id] = {
                "clean_slab_energy_ev": float(energy),
                "calculation_type": "clean_slab_relax",
                "slurm_job_id": str(record.get("slurm_job_id", "")),
                "parsed_field": "final_toten_ev",
                "energy_unit": "eV",
                "data_version": "c12-clean-slab-energy-v1",
            }

    required_slab_ids = {
        str(
            result.get("scientific_identity", {}).get(
                "source_clean_slab_id",
                "",
            )
        ).strip()
        for result in adsorption_results
        if isinstance(result, dict)
        and isinstance(result.get("scientific_identity", {}), dict)
    }
    required_slab_ids.discard("")

    required_adsorbates = {
        str(
            result.get("scientific_identity", {}).get(
                "adsorbate",
                "",
            )
        ).strip()
        for result in adsorption_results
        if isinstance(result, dict)
        and isinstance(result.get("scientific_identity", {}), dict)
    }
    required_adsorbates.discard("")

    catalog_resolved_adsorbates = []
    for adsorbate in sorted(required_adsorbates):
        if adsorbate in reference_energies:
            continue
        resolved = reference_energy_catalog.resolve(adsorbate)
        if resolved is not None:
            reference_energies[adsorbate] = resolved
            catalog_resolved_adsorbates.append(adsorbate)

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
    identity_incomplete = bool(adsorption_results) and (
        not required_slab_ids or not required_adsorbates
    )
    ready = (
        bool(adsorption_results)
        and not identity_incomplete
        and not missing_slab_ids
        and not missing_references
    )
    status = (
        "adsorption_energy_inputs_ready"
        if ready
        else "adsorption_energy_inputs_required"
    )
    preparation = {
        "schema_version": "c12.7-input-v1",
        "stage": "c12.7_energy_input_preparation",
        "status": status,
        "adsorption_result_count": len(adsorption_results),
        "clean_slab_energy_count": len(clean_slab_energies),
        "reference_energy_count": len(reference_energies),
        "required_clean_slab_ids": sorted(required_slab_ids),
        "required_adsorbates": sorted(required_adsorbates),
        "missing_clean_slab_ids": missing_slab_ids,
        "missing_reference_energies": missing_references,
        "catalog_resolved_adsorbates": catalog_resolved_adsorbates,
        "user_input_required_for_unlisted_references": bool(
            missing_references
        ),
        "scientific_identity_incomplete": identity_incomplete,
        "calculation_performed": False,
        "next_stage": (
            "c12.7_adsorption_energy"
            if ready
            else "human_energy_input"
        ),
    }

    persisted = {}
    if task_id:
        persisted = WorkflowRunRepository().update(
            task_id,
            {
                "workflow_status": status,
                "resume_stage": "c12.7_adsorption_energy",
                "last_completed_stage": (
                    "c12.7_energy_input_preparation"
                ),
                "adsorption_parsed_results": adsorption_results,
                "clean_slab_energies": clean_slab_energies,
                "reference_energies": reference_energies,
                "adsorption_energy_input_preparation": preparation,
                "terminal": False,
            },
        )

    return {
        "adsorption_energy_input_preparation": preparation,
        "clean_slab_energies": clean_slab_energies,
        "reference_energies": reference_energies,
        "workflow_run": persisted,
        "status": status,
    }


def adsorption_energy_review_and_persist_node(
    state: AdsorptionJobOperationState,
) -> dict[str, Any]:
    """Run the C12.7 human gate and persist its terminal result."""

    result = adsorption_energy_review_node(state)
    review = result.get("adsorption_energy_review", {})
    review_status = str(review.get("status", ""))
    review_completed = review_status == (
        "adsorption_energy_review_completed"
    )
    task_id = str(state.get("task_id", "")).strip()
    workflow = {}

    if task_id:
        workflow = WorkflowRunRepository().update(
            task_id,
            {
                "workflow_status": result.get(
                    "status",
                    "adsorption_energy_review_failed",
                ),
                "resume_stage": (
                    None
                    if review_completed
                    else "c12.7_adsorption_energy"
                ),
                "last_completed_stage": (
                    "c12.7_adsorption_energy_review"
                ),
                "adsorption_energy_calculation": state.get(
                    "adsorption_energy_calculation",
                    {},
                ),
                "adsorption_energy_review": review,
                "approved_adsorption_energies": result.get(
                    "approved_adsorption_energies",
                    [],
                ),
                "terminal": review_completed,
            },
        )

    return {
        **result,
        "workflow_run": workflow,
    }


def route_after_source_filter(
    state: AdsorptionJobOperationState,
) -> Literal["monitor", "end"]:
    return (
        "monitor"
        if state.get("slurm_job_ids")
        else "end"
    )


def route_after_download_review(
    state: AdsorptionJobOperationState,
) -> Literal["download", "diagnose"]:
    return (
        "download"
        if state.get("download_review", {}).get("status")
        == "result_download_approved"
        else "diagnose"
    )


def route_after_download(
    state: AdsorptionJobOperationState,
) -> Literal["parse", "end"]:
    """Stop safely when no adsorption result was downloaded."""

    jobs = state.get("download_result", {}).get("jobs", [])
    return "parse" if isinstance(jobs, list) and jobs else "end"


def route_after_result_ready(
    state: AdsorptionJobOperationState,
) -> Literal["energy_input", "diagnose"]:
    return (
        "energy_input"
        if state.get("adsorption_result_ready", {}).get(
            "status"
        ) == "adsorption_results_ready"
        else "diagnose"
    )


def route_after_energy_input(
    state: AdsorptionJobOperationState,
) -> Literal["calculate", "end"]:
    return (
        "calculate"
        if state.get(
            "adsorption_energy_input_preparation",
            {},
        ).get("status") == "adsorption_energy_inputs_ready"
        else "end"
    )


def route_after_diagnosis(
    state: AdsorptionJobOperationState,
) -> Literal["retry_review", "end"]:
    return (
        "retry_review"
        if state.get("diagnosis_result", {}).get(
            "retry_candidate_count",
            0,
        )
        else "end"
    )


def build_adsorption_job_operations_graph(
    checkpointer=None,
):
    """Build C12.6 monitoring without bulk-energy backfill."""

    builder = StateGraph(AdsorptionJobOperationState)
    for name, node in (
        ("source_filter", adsorption_source_filter_node),
        ("monitor", adsorption_monitor_node),
        ("completion", adsorption_completion_node),
        ("download_review", download_review_node),
        ("download", download_node),
        ("parse", parse_node),
        ("result_ready", adsorption_result_ready_node),
        ("adsorption_energy_input", adsorption_energy_input_node),
        (
            "adsorption_energy_calculation",
            adsorption_energy_calculation_node,
        ),
        (
            "adsorption_energy_review",
            adsorption_energy_review_and_persist_node,
        ),
        ("diagnosis", diagnosis_node),
        ("retry_review", retry_review_node),
    ):
        builder.add_node(name, node)

    builder.add_edge(START, "source_filter")
    builder.add_conditional_edges(
        "source_filter",
        route_after_source_filter,
        {"monitor": "monitor", "end": END},
    )
    builder.add_edge("monitor", "completion")
    builder.add_edge("completion", "download_review")
    builder.add_conditional_edges(
        "download_review",
        route_after_download_review,
        {"download": "download", "diagnose": "diagnosis"},
    )
    builder.add_conditional_edges(
        "download",
        route_after_download,
        {"parse": "parse", "end": END},
    )
    builder.add_edge("parse", "result_ready")
    builder.add_conditional_edges(
        "result_ready",
        route_after_result_ready,
        {
            "energy_input": "adsorption_energy_input",
            "diagnose": "diagnosis",
        },
    )
    builder.add_conditional_edges(
        "adsorption_energy_input",
        route_after_energy_input,
        {
            "calculate": "adsorption_energy_calculation",
            "end": END,
        },
    )
    builder.add_edge(
        "adsorption_energy_calculation",
        "adsorption_energy_review",
    )
    builder.add_edge("adsorption_energy_review", END)
    builder.add_conditional_edges(
        "diagnosis",
        route_after_diagnosis,
        {"retry_review": "retry_review", "end": END},
    )
    builder.add_edge("retry_review", END)

    return builder.compile(
        checkpointer=checkpointer or InMemorySaver()
    )


adsorption_job_operations_graph = (
    build_adsorption_job_operations_graph()
)


def build_adsorption_energy_resume_graph(
    checkpointer=None,
):
    """Resume C12.7 directly from persisted three-energy inputs."""

    builder = StateGraph(AdsorptionJobOperationState)
    builder.add_node(
        "adsorption_energy_calculation",
        adsorption_energy_calculation_node,
    )
    builder.add_node(
        "adsorption_energy_review",
        adsorption_energy_review_and_persist_node,
    )
    builder.add_edge(
        START,
        "adsorption_energy_calculation",
    )
    builder.add_edge(
        "adsorption_energy_calculation",
        "adsorption_energy_review",
    )
    builder.add_edge(
        "adsorption_energy_review",
        END,
    )
    return builder.compile(
        checkpointer=checkpointer or InMemorySaver()
    )


adsorption_energy_resume_graph = (
    build_adsorption_energy_resume_graph()
)
