from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graph.cli import (
    collect_adsorption_structure_review,
    collect_dft_input_review_decision,
)
from app.graph.job_operations import async_adsorption_dft_finalize_node
from app.graph.nodes import (
    adsorption_dft_preview_node,
    adsorption_dft_review_node,
    adsorption_dft_revision_apply_node,
    adsorption_dft_revision_plan_node,
    adsorption_structure_quality_node,
    adsorption_structure_review_node,
)
from app.graph.routes import route_after_adsorption_dft_review
from app.graph.state import CatalystState
from app.workflow_resume_cli import load_workflow, resume_workflow


def load_structures(task_id: str) -> list[dict[str, Any]]:
    root = Path("data/adsorption_structures") / task_id
    if not root.is_dir():
        raise FileNotFoundError(
            f"Adsorption structure directory does not exist: {root}"
        )
    structures = []
    for metadata_path in sorted(root.rglob("metadata.json")):
        value = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            continue
        value["metadata_path"] = str(metadata_path.resolve())
        value["poscar_path"] = str((metadata_path.parent / "POSCAR").resolve())
        value["output_directory"] = str(metadata_path.parent.resolve())
        value["eligible_for_c12_4_quality"] = (
            (metadata_path.parent / "POSCAR").is_file()
            and value.get("adsorbate_instance_count") == 1
            and value.get("coadsorption") is False
        )
        structures.append(value)
    if not structures:
        raise ValueError(f"No C12.3 structures were found for {task_id}")
    return structures


def build_resume_graph():
    builder = StateGraph(CatalystState)
    for name, node in (
        ("adsorption_structure_quality", adsorption_structure_quality_node),
        ("adsorption_structure_review", adsorption_structure_review_node),
        ("adsorption_dft_preview", adsorption_dft_preview_node),
        ("adsorption_dft_review", adsorption_dft_review_node),
        ("adsorption_dft_revision_plan", adsorption_dft_revision_plan_node),
        ("adsorption_dft_revision_apply", adsorption_dft_revision_apply_node),
        ("adsorption_dft_finalize", async_adsorption_dft_finalize_node),
    ):
        builder.add_node(name, node)
    builder.add_edge(START, "adsorption_structure_quality")
    builder.add_edge("adsorption_structure_quality", "adsorption_structure_review")
    builder.add_edge("adsorption_structure_review", "adsorption_dft_preview")
    builder.add_edge("adsorption_dft_preview", "adsorption_dft_review")
    builder.add_conditional_edges(
        "adsorption_dft_review",
        route_after_adsorption_dft_review,
        {
            "revise": "adsorption_dft_revision_plan",
            "finalize": "adsorption_dft_finalize",
        },
    )
    builder.add_edge("adsorption_dft_revision_plan", "adsorption_dft_revision_apply")
    builder.add_edge("adsorption_dft_revision_apply", "adsorption_dft_review")
    builder.add_edge("adsorption_dft_finalize", END)
    return builder.compile(checkpointer=InMemorySaver())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resume C12.4-C12.5 from existing C12.3 structures"
    )
    parser.add_argument("task_id")
    parser.add_argument(
        "--stop-after-c12-5",
        action="store_true",
        help="Create the approved five files without entering C12.6",
    )
    args = parser.parse_args()
    graph = build_resume_graph()
    config = {"configurable": {"thread_id": f"c12-structure-resume-{args.task_id}"}}
    result = graph.invoke(
        {
            "task_id": args.task_id,
            "adsorption_structures": load_structures(args.task_id),
            "errors": [],
            "warnings": [],
        },
        config=config,
    )
    while "__interrupt__" in result:
        request = result["__interrupt__"][0].value
        kind = request.get("type")
        if kind == "adsorption_structure_review_required":
            decision = collect_adsorption_structure_review(request)
        elif kind == "adsorption_dft_input_review_required":
            decision = collect_dft_input_review_decision({
                **request,
                "stage_label": "C12.5",
            })
        else:
            raise RuntimeError(f"Unsupported interrupt: {kind}")
        result = graph.invoke(Command(resume=decision), config=config)
    for key in (
        "adsorption_structure_quality",
        "adsorption_structure_review",
        "adsorption_dft_input_preview",
        "adsorption_dft_input_review",
        "adsorption_dft_input_preparation",
        "workflow_run",
    ):
        if key in result:
            print(f"\n{'=' * 70}\n{key}\n{'=' * 70}")
            print(json.dumps(result[key], ensure_ascii=False, indent=2))
    print(f"\nfinal: {result.get('status')}")

    if (
        not args.stop_after_c12_5
        and result.get("status") == "dft_input_preparation_completed"
    ):
        print(
            "\nC12.5 completed; continuing to C12.6 adsorption "
            "submission with all human gates enabled."
        )
        next_result = resume_workflow(
            load_workflow(args.task_id),
            f"c12-structure-resume-{args.task_id}-c12-6",
        )
        print(
            f"\nC12.6 final: {next_result.get('status')}"
        )


if __name__ == "__main__":
    main()
