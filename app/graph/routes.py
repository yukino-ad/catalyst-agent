from __future__ import annotations

from typing import Literal

from app.graph.state import CatalystState
from tools.literature.retry_support import accepted_five_metal_sets


def route_after_task_analysis(
    state: CatalystState,
) -> Literal["external_c", "direct_c", "normal"]:
    """Skip B only for a validated explicit five-metal HEA modeling task."""

    external = state.get("external_structure_request", {})
    if isinstance(external, dict) and external.get("requested", False):
        return "external_c"
    decision = state.get("direct_c_stage", {})
    if isinstance(decision, dict) and decision.get("requested", False):
        return "direct_c"
    return "normal"


def route_after_external_structure_input(
    state: CatalystState,
) -> Literal["formation", "stability", "end"]:
    result = state.get("external_structure_ingestion", {})
    if result.get("status") not in {
        "external_structure_ready_for_c6",
        "external_structure_ready_for_c7",
    }:
        return "end"
    structure = result.get("structure", {})
    return (
        "stability"
        if structure.get("formation_energy") is not None
        else "formation"
    )


def route_after_literature_evidence(
    state: CatalystState,
) -> Literal["extract", "online_failure"]:
    """Do not let a mandatory B4 failure fall back to local-only evidence."""

    policy = state.get("online_search_policy", {})
    online = state.get("online_literature_result", {})
    if (
        policy.get("decision") == "online_required"
        and online.get("status") == "online_failed"
    ):
        return "online_failure"
    return "extract"


def route_after_literature_commit(
    state: CatalystState,
) -> Literal["retry_online", "continue"]:
    """Retry B3-B6 until a reviewed explicit five-metal HEA is found."""

    review = state.get("literature_review", {})
    online = state.get("online_literature_result", {})
    candidate_count = int(review.get("candidate_count", 0) or 0)
    deferred_count = int(review.get("deferred_count", 0) or 0)
    if candidate_count <= 0 or deferred_count > 0:
        return "continue"
    if online.get("status") not in {"completed", "completed_no_results"}:
        return "continue"

    assertions = [
        *state.get("accepted_literature_assertion_history", []),
        *state.get("accepted_literature_assertions", []),
    ]
    papers = [
        *state.get("accepted_literature_papers", []),
        *review.get("accepted", []),
    ]
    if accepted_five_metal_sets(
        assertions,
        state.get("task_analysis", {}),
        papers,
    ):
        return "continue"

    round_number = int(state.get("literature_search_round", 1) or 1)
    max_rounds = int(state.get("literature_max_search_rounds", 3) or 3)
    if round_number < max_rounds:
        return "retry_online"
    return "continue"


def route_after_c_stage_execution_review(
    state: CatalystState,
) -> Literal["structure", "end"]:
    """Require explicit approval before any C5+ theoretical work."""

    mode = state.get("c_stage_execution_mode", "candidate_only")
    if mode in {"fcc_only", "stability_screening", "dft_validation"}:
        return "structure"
    return "end"


def route_after_structure_modeling(
    state: CatalystState,
) -> Literal["formation_energy", "end"]:
    """Stop after C5 when the user approved FCC modeling only."""

    if state.get("c_stage_execution_mode") in {
        "stability_screening", "dft_validation"
    }:
        return "formation_energy"
    return "end"


def route_after_stability_screening(
    state: CatalystState,
) -> Literal["review", "slab", "end"]:
    """Route C7-passed structures according to the approved C-stage scope."""

    eligible = state.get("slab_eligible_structures", [])
    if not isinstance(eligible, list) or not eligible:
        return "end"
    mode = state.get("c_stage_execution_mode")
    if mode == "dft_validation":
        return "slab"
    if mode == "stability_screening":
        return "review"
    return "end"


def route_after_c7_dft_upgrade_review(
    state: CatalystState,
) -> Literal["slab", "end"]:
    """Continue only with structures explicitly selected after C7."""

    selected = state.get("dft_selected_stability_structures", [])
    if isinstance(selected, list) and selected:
        return "slab"
    return "end"


def route_after_planner(
    state: CatalystState,
) -> Literal["rag", "skip_rag"]:
    """根据 Router 的决定选择 RAG 分支。"""

    route = state.get("route", {})

    if route.get("use_rag") is True:
        return "rag"

    return "skip_rag"
    
def route_after_literature_summary(
    state: CatalystState,
) -> Literal["candidate_design", "end"]:
    """Decide whether the task should enter C-stage design."""

    context = state.get(
        "canonical_task_context",
        {},
    )
    if context.get("requires_clarification", False) is True:
        return "end"

    contract = state.get("literature_evidence_contract", {})
    if not contract.get("evidence_backed_candidate_ready", False):
        return "end"

    task_analysis = state.get(
        "task_analysis",
        {},
    )

    if task_analysis.get("needs_candidate_design", False) is True:
        return "candidate_design"

    return "end"


def route_after_dft_input_review(
    state: CatalystState,
) -> Literal["revise", "finalize"]:
    """Send requested edits through validation before another review."""

    review = state.get("dft_input_review", {})
    if review.get("action") == "revise":
        return "revise"
    return "finalize"


def route_after_adsorption_dft_review(
    state: CatalystState,
) -> Literal["revise", "finalize"]:
    """Route C12.5 review through revision or finalization."""

    review = state.get(
        "adsorption_dft_input_review",
        {},
    )

    if review.get("action") == "revise":
        return "revise"

    return "finalize"


def route_after_formation_energy(
    state: CatalystState,
) -> Literal["bulk_dft", "source_review"]:
    """Pause for bulk DFT inputs when C6 leaves an external queue."""

    if (
        state.get("c_stage_execution_mode") == "dft_validation"
        and state.get("dft_formation_energy_queue")
    ):
        return "bulk_dft"
    return "source_review"


def route_after_formation_energy_source_review(
    state: CatalystState,
) -> Literal["stability", "end"]:
    """Do not enter C7 until one complete source has been approved."""

    if state.get("selected_formation_energy_source") in {
        "pretrained",
        "temporary_trained",
        "external_user_provided",
    } and state.get("selected_formation_energy_structures"):
        return "stability"
    return "end"


def route_after_bulk_dft_review(
    state: CatalystState,
) -> Literal["revise", "finalize"]:
    """Route C6D review to revision or atomic finalization."""

    review = state.get("bulk_dft_input_review", {})
    if review.get("action") == "revise":
        return "revise"
    return "finalize"


def route_after_dft_execution_options(
    state: CatalystState,
) -> Literal["preflight", "end"]:
    """Continue to C11.2 or stop when the user defers submission."""

    options = state.get("dft_execution_options", {})
    if options.get("action") == "continue":
        return "preflight"
    return "end"


def route_after_dft_local_preflight(
    state: CatalystState,
) -> Literal["cluster_preflight", "end"]:
    """Only a fully passed non-empty batch may enter C11.3."""

    result = state.get("dft_local_preflight", {})
    if (
        result.get("status")
        == "dft_local_preflight_passed"
        and result.get("job_count", 0) > 0
    ):
        return "cluster_preflight"
    return "end"


def route_after_cluster_readonly_preflight(
    state: CatalystState,
) -> Literal["remote_plan", "end"]:
    """Only passed C11.3 jobs may enter C11.4."""

    result = state.get(
        "cluster_readonly_preflight",
        {},
    )
    jobs = state.get(
        "cluster_preflight_jobs",
        [],
    )

    if (
        result.get("status")
        == "cluster_readonly_preflight_passed"
        and isinstance(jobs, list)
        and bool(jobs)
    ):
        return "remote_plan"

    return "end"


def route_after_remote_execution_plan(
    state: CatalystState,
) -> Literal["upload_review", "end"]:
    """Only a ready plan may request upload approval."""

    plan = state.get(
        "remote_execution_plan",
        {},
    )

    if (
        plan.get("status")
        == "remote_execution_plan_ready"
        and plan.get("job_count", 0) > 0
    ):
        return "upload_review"

    return "end"


def route_after_remote_upload_review(
    state: CatalystState,
) -> Literal["upload", "end"]:
    """Only explicit upload approval may write remotely."""

    review = state.get(
        "remote_upload_review",
        {},
    )

    if (
        review.get("status")
        == "remote_upload_approved"
        and review.get("approved_job_ids")
    ):
        return "upload"

    return "end"


def route_after_remote_upload(
    state: CatalystState,
) -> Literal["submission_review", "end"]:
    """Only fully verified uploads may be reviewed."""

    result = state.get(
        "remote_upload_result",
        {},
    )
    jobs = state.get(
        "remote_verified_jobs",
        [],
    )

    if (
        result.get("status")
        == "remote_upload_verified"
        and isinstance(jobs, list)
        and bool(jobs)
    ):
        return "submission_review"

    return "end"


def route_after_remote_submission_review(
    state: CatalystState,
) -> Literal["submit", "end"]:
    """Only explicit sbatch approval may submit."""

    review = state.get(
        "remote_submission_review",
        {},
    )

    if (
        review.get("status")
        == "remote_submission_approved"
        and review.get("approved_job_ids")
    ):
        return "submit"

    return "end"
