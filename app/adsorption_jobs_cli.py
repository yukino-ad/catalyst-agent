from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from langgraph.types import Command

from app.cluster_jobs_cli import collect_download, collect_retry
from app.graph.adsorption_execution_workflow import (
    adsorption_execution_graph,
)
from app.graph.adsorption_job_operations import (
    adsorption_job_operations_graph,
)
from app.graph.cli import (
    collect_adsorption_dft_execution,
    collect_remote_submission_review,
    collect_remote_upload_review,
)


def show(title: str, value: Any) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _load_state(path: str) -> dict[str, Any]:
    target = Path(path).resolve()
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("C12.5 state JSON must be an object")
    jobs = value.get("adsorption_dft_jobs", [])
    preview = value.get("adsorption_dft_input_preview", {})
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("State contains no C12.5 adsorption_dft_jobs")
    if not isinstance(preview, dict) or not preview.get("bundles"):
        raise ValueError("State contains no C12.5 preview bundles")
    return value


def _resume(graph, result, config):
    while "__interrupt__" in result:
        request = result["__interrupt__"][0].value
        interrupt_type = request.get("type")
        if interrupt_type == "adsorption_dft_execution_required":
            decision = collect_adsorption_dft_execution(request)
        elif interrupt_type == "remote_upload_review_required":
            decision = collect_remote_upload_review(request)
        elif interrupt_type == "remote_submission_review_required":
            decision = collect_remote_submission_review(request)
        elif interrupt_type == "result_download_review_required":
            decision = collect_download(request)
        elif interrupt_type == "retry_plan_review_required":
            decision = collect_retry(request)
        else:
            raise RuntimeError(
                f"Unsupported C12.6 interrupt: {interrupt_type}"
            )
        result = graph.invoke(
            Command(resume=decision),
            config=config,
        )
    return result


def _submit(state_path: str, thread_id: str) -> dict[str, Any]:
    state = _load_state(state_path)
    config = {"configurable": {"thread_id": thread_id}}
    result = adsorption_execution_graph.invoke(
        {
            **state,
            "errors": state.get("errors", []),
            "warnings": state.get("warnings", []),
        },
        config=config,
    )
    return _resume(adsorption_execution_graph, result, config)


def _poll(job_ids: list[str], thread_id: str) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    result = adsorption_job_operations_graph.invoke(
        {
            "requested_slurm_job_ids": job_ids,
            "errors": [],
            "status": "created",
        },
        config=config,
    )
    return _resume(adsorption_job_operations_graph, result, config)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit or monitor C12.6 adsorption DFT jobs"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument(
        "state_json",
        help="JSON state containing C12.5 preview and finalized jobs",
    )
    submit_parser.add_argument("--thread-id", default="")

    poll_parser = subparsers.add_parser("poll")
    poll_parser.add_argument("job_ids", nargs="*")
    poll_parser.add_argument("--thread-id", default="")

    args = parser.parse_args()
    if args.action == "poll" and any(
        not value.isdigit() for value in args.job_ids
    ):
        raise ValueError("Every Slurm job ID must contain digits only")

    thread_id = args.thread_id.strip() or (
        f"adsorption-{args.action}-{uuid.uuid4().hex[:12]}"
    )
    if args.action == "submit":
        result = _submit(args.state_json, thread_id)
    else:
        result = _poll(args.job_ids, thread_id)

    for key in (
        "dft_execution_options",
        "dft_local_preflight",
        "cluster_readonly_preflight",
        "remote_execution_plan",
        "remote_upload_result",
        "remote_submission_result",
        "submission_recording",
        "source_filter",
        "monitor_result",
        "completion_result",
        "download_result",
        "parse_result",
        "adsorption_result_ready",
        "diagnosis_result",
        "retry_reviews",
        "workflow_run",
    ):
        if key in result:
            show(key, result[key])
    show("final", {"status": result.get("status")})


if __name__ == "__main__":
    main()
