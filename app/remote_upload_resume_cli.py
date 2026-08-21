from __future__ import annotations

import argparse
import json
from typing import Any

from langgraph.types import Command

from app.graph.cli import (
    collect_remote_submission_review,
    collect_remote_upload_review,
)
from app.graph.workflow import build_graph


def show(title: str, value: Any) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def resume_remote_upload(thread_id: str) -> dict[str, Any]:
    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    state = dict(snapshot.values or {})
    plan = state.get("remote_execution_plan", {})
    review = state.get("remote_upload_review", {})
    if not isinstance(plan, dict) or plan.get("status") != "remote_execution_plan_ready":
        raise ValueError("Checkpoint has no ready remote execution plan")
    if not isinstance(review, dict) or review.get("status") not in {
        "remote_upload_approved",
        "remote_upload_deferred",
    }:
        raise ValueError(
            "Checkpoint has no resumable remote upload review; "
            "expected remote_upload_approved or remote_upload_deferred"
        )

    # Re-enter the review gate. Deferred reviews must not be converted into an
    # approval implicitly; the user must confirm the full UPLOAD phrase again.
    update = graph.update_state(
        config,
        {
            "remote_upload_review": {},
            "remote_upload_result": {},
            "remote_verified_jobs": [],
            "remote_submission_review": {},
            "remote_submission_result": {},
            "status": "remote_upload_resume_requested",
        },
        as_node="remote_execution_plan",
    )
    result = graph.invoke(None, config=update or config)
    while "__interrupt__" in result:
        interrupts = result.get("__interrupt__", ())
        if not interrupts:
            raise RuntimeError("LangGraph returned an empty interrupt")
        request = interrupts[0].value
        request_type = request.get("type")
        if request_type == "remote_upload_review_required":
            decision = collect_remote_upload_review(request)
        elif request_type == "remote_submission_review_required":
            decision = collect_remote_submission_review(request)
        else:
            raise RuntimeError("Unexpected resume interrupt: " + str(request_type))
        result = graph.invoke(Command(resume=decision), config=config)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resume a partially uploaded C11.4 batch from checkpoint."
    )
    parser.add_argument("thread_id")
    args = parser.parse_args()
    result = resume_remote_upload(args.thread_id.strip())
    show("remote_upload_result", result.get("remote_upload_result", {}))
    show("remote_submission_result", result.get("remote_submission_result", {}))
    show("final", {"task_id": result.get("task_id"), "status": result.get("status")})
    try:
        from app.job_monitor_launcher import launch_job_monitor

        monitor = launch_job_monitor(result)
        if monitor.get("status") == "monitor_launched":
            print(
                "\nOpened an independent job monitor window for: "
                + ", ".join(monitor.get("slurm_job_ids", []))
            )
    except Exception as error:
        print(
            "\nSubmission succeeded, but the monitor window could not be opened: "
            f"{type(error).__name__}: {error}"
        )


if __name__ == "__main__":
    main()
