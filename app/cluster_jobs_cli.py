from __future__ import annotations

import argparse
import json
import uuid
from typing import Any

from langgraph.types import Command

from app.graph.job_operations import job_operations_graph
from app.graph.cli import (
    collect_adsorption_structure_review,
    collect_adsorption_intermediate_review,
    collect_dft_input_review_decision,
    collect_slab_review_decision,
)


def show(title: str, value: Any) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def collect_download(request: dict[str, Any]) -> dict[str, Any]:
    show("C11.5.4 result download review", request)
    expected = str(request.get("confirmation_phrase", ""))
    value = input(f"Enter {expected}, or press Enter to defer:\n> ").strip()
    ids = [str(job["slurm_job_id"]) for job in request.get("jobs", [])]
    return {
        "action": "approve_download" if value == expected else "defer",
        "approved_slurm_job_ids": ids if value == expected else [],
        "confirmation_text": value,
    }


def collect_retry(request: dict[str, Any]) -> dict[str, Any]:
    show("C11.5.6 retry plan review", request)
    decisions = {}
    for job in request.get("jobs", []):
        job_id = str(job["slurm_job_id"])
        expected = f"RETRY {job_id}"
        value = input(f"Enter {expected} to approve its plan, or Enter to defer:\n> ").strip()
        decisions[job_id] = {
            "action": "approve_retry_plan" if value == expected else "defer",
            "confirmation_text": value,
        }
    return {"decisions": decisions}


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor persisted catalyst DFT jobs")
    parser.add_argument("action", choices=["poll"])
    parser.add_argument("job_ids", nargs="*", help="Optional numeric Slurm job IDs")
    parser.add_argument(
        "--thread-id",
        default="",
        help="Stable LangGraph thread ID for resuming a prior monitoring run",
    )
    args = parser.parse_args()
    if any(not value.isdigit() for value in args.job_ids):
        raise ValueError("Every Slurm job ID must contain digits only")
    thread_id = args.thread_id.strip() or f"monitor-{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": thread_id}}
    result = job_operations_graph.invoke(
        {"slurm_job_ids": args.job_ids, "errors": [], "status": "created"},
        config=config,
    )
    while "__interrupt__" in result:
        request = result["__interrupt__"][0].value
        if request.get("type") == "result_download_review_required":
            decision = collect_download(request)
        elif request.get("type") == "retry_plan_review_required":
            decision = collect_retry(request)
        elif request.get("type") == "slab_review_required":
            decision = collect_slab_review_decision(request)
        elif request.get("type") == "dft_input_review_required":
            decision = collect_dft_input_review_decision(request)
        elif (
            request.get("type")
            == "adsorption_structure_review_required"
        ):
            decision = collect_adsorption_structure_review(
                request
            )
        elif (
            request.get("type")
            == "adsorption_intermediate_review_required"
        ):
            decision = collect_adsorption_intermediate_review(request)
        elif (
            request.get("type")
            == "adsorption_dft_input_review_required"
        ):
            decision = collect_dft_input_review_decision({
                **request,
                "stage_label": "C12.5",
            })
        else:
            raise RuntimeError(f"Unsupported interrupt: {request.get('type')}")
        result = job_operations_graph.invoke(Command(resume=decision), config=config)
    for key in (
        "monitor_result", "completion_result", "download_result",
        "parse_result", "diagnosis_result", "retry_reviews",
        "formation_energy_backfill", "async_stability_screening",
        "slab_generation", "slab_quality", "slab_review",
        "dft_input_preparation", "clean_slab_result_readiness",
        "adsorption_reaction_plan", "adsorption_site_generation",
        "adsorbate_structure_generation",
        "adsorption_structure_quality",
        "adsorption_structure_review",
        "adsorption_dft_input_preview",
        "adsorption_dft_input_review",
        "adsorption_dft_input_preparation",
        "workflow_run",
    ):
        if key in result:
            show(key, result[key])
    show("final", {"status": result.get("status")})


if __name__ == "__main__":
    main()
