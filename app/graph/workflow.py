from __future__ import annotations

from langgraph.checkpoint.memory import (
    InMemorySaver,
)
from langgraph.graph import (
    END,
    START,
    StateGraph,
)

from app.graph.nodes import (
    bulk_dft_input_finalize_node,
    bulk_dft_input_preview_node,
    bulk_dft_input_review_node,
    bulk_dft_revision_apply_node,
    bulk_dft_revision_plan_node,
    candidate_generation_node,
    candidate_review_node,
    c7_dft_upgrade_review_node,
    c_stage_execution_review_node,
    capability_gate_node,
    c_stage_preparation_node,
    cluster_readonly_preflight_node,
    dft_input_finalize_node,
    dft_input_preview_node,
    dft_input_review_node,
    dft_execution_options_node,
    dft_local_preflight_node,
    dft_revision_apply_node,
    dft_revision_plan_node,
    formation_energy_node,
    formation_energy_source_review_node,
    external_structure_input_node,
    literature_commit_node,
    literature_evidence_node,
    literature_online_failure_node,
    literature_assertion_extraction_node,
    literature_retry_prepare_node,
    literature_review_finalize_node,
    literature_review_node,
    literature_summary_node,
    planner_node,
    reviewed_rag_node,
    remote_execution_plan_node,
    remote_submission_node,
    remote_submission_review_node,
    remote_upload_node,
    remote_upload_review_node,
    router_node,
    skip_rag_node,
    slab_generation_node,
    slab_quality_node,
    slab_review_node,
    stability_screening_node,
    structure_modeling_node,
    submission_record_node,
    task_analysis_node,
)
from app.graph.routes import (
    route_after_bulk_dft_review,
    route_after_c7_dft_upgrade_review,
    route_after_c_stage_execution_review,
    route_after_dft_input_review,
    route_after_dft_execution_options,
    route_after_dft_local_preflight,
    route_after_cluster_readonly_preflight,
    route_after_remote_execution_plan,
    route_after_remote_submission_review,
    route_after_remote_upload,
    route_after_remote_upload_review,
    route_after_formation_energy,
    route_after_formation_energy_source_review,
    route_after_external_structure_input,
    route_after_literature_evidence,
    route_after_literature_commit,
    route_after_literature_summary,
    route_after_task_analysis,
    route_after_planner,
    route_after_stability_screening,
    route_after_structure_modeling,
)
from app.graph.state import CatalystState
from app.graph.checkpointing import persistent_checkpointer


def build_graph(checkpointer=None):
    """构建带文献人工审查的科研 LangGraph。"""

    builder = StateGraph(
        CatalystState
    )

    builder.add_node(
        "task_analysis",
        task_analysis_node,
    )

    builder.add_node(
        "external_structure_input",
        external_structure_input_node,
    )

    builder.add_node(
        "capability_gate",
        capability_gate_node,
    )

    builder.add_node(
        "router",
        router_node,
    )

    builder.add_node(
        "planner",
        planner_node,
    )

    builder.add_node(
        "literature_evidence",
        literature_evidence_node,
    )

    builder.add_node(
        "literature_online_failure",
        literature_online_failure_node,
    )

    builder.add_node(
        "literature_review",
        literature_review_node,
    )

    builder.add_node(
        "literature_commit",
        literature_commit_node,
    )

    builder.add_node(
        "literature_retry_prepare",
        literature_retry_prepare_node,
    )

    builder.add_node(
        "literature_review_finalize",
        literature_review_finalize_node,
    )

    builder.add_node(
        "reviewed_rag",
        reviewed_rag_node,
    )
    
    builder.add_node(
        "skip_rag",
        skip_rag_node,
    )

    builder.add_node(
        "literature_summary",
        literature_summary_node,
    )

    builder.add_node(
        "literature_assertion_extraction",
        literature_assertion_extraction_node,
    )

    builder.add_node(
        "c_stage_preparation",
        c_stage_preparation_node,
    )

    builder.add_node(
        "candidate_generation",
        candidate_generation_node,
    )

    builder.add_node(
        "candidate_review",
        candidate_review_node,
    )

    builder.add_node(
        "c_stage_execution_review",
        c_stage_execution_review_node,
    )

    builder.add_node(
        "structure_modeling",
        structure_modeling_node,
    )

    builder.add_node(
        "formation_energy",
        formation_energy_node,
    )

    builder.add_node(
        "formation_energy_source_review",
        formation_energy_source_review_node,
    )

    builder.add_node(
        "bulk_dft_input_preview",
        bulk_dft_input_preview_node,
    )

    builder.add_node(
        "bulk_dft_input_review",
        bulk_dft_input_review_node,
    )

    builder.add_node(
        "bulk_dft_revision_plan",
        bulk_dft_revision_plan_node,
    )

    builder.add_node(
        "bulk_dft_revision_apply",
        bulk_dft_revision_apply_node,
    )

    builder.add_node(
        "bulk_dft_input_finalize",
        bulk_dft_input_finalize_node,
    )

    builder.add_node(
        "dft_execution_options",
        dft_execution_options_node,
    )

    builder.add_node(
        "dft_local_preflight",
        dft_local_preflight_node,
    )

    builder.add_node(
        "cluster_readonly_preflight",
        cluster_readonly_preflight_node,
    )

    builder.add_node(
        "remote_execution_plan",
        remote_execution_plan_node,
    )

    builder.add_node(
        "remote_upload_review",
        remote_upload_review_node,
    )

    builder.add_node(
        "remote_upload",
        remote_upload_node,
    )

    builder.add_node(
        "remote_submission_review",
        remote_submission_review_node,
    )

    builder.add_node(
        "remote_submission",
        remote_submission_node,
    )

    builder.add_node(
        "submission_record",
        submission_record_node,
    )

    builder.add_node(
        "stability_screening",
        stability_screening_node,
    )

    builder.add_node(
        "c7_dft_upgrade_review",
        c7_dft_upgrade_review_node,
    )

    builder.add_node(
        "slab_generation",
        slab_generation_node,
    )

    builder.add_node(
        "slab_quality",
        slab_quality_node,
    )

    builder.add_node(
        "slab_review",
        slab_review_node,
    )

    builder.add_node(
        "dft_input_preview",
        dft_input_preview_node,
    )

    builder.add_node(
        "dft_input_review",
        dft_input_review_node,
    )

    builder.add_node(
        "dft_input_finalize",
        dft_input_finalize_node,
    )

    builder.add_node(
        "dft_revision_plan",
        dft_revision_plan_node,
    )

    builder.add_node(
        "dft_revision_apply",
        dft_revision_apply_node,
    )

    builder.add_edge(
        START,
        "task_analysis",
    )

    builder.add_conditional_edges(
        "task_analysis",
        route_after_task_analysis,
        {
            "external_c": "external_structure_input",
            "direct_c": "c_stage_preparation",
            "normal": "capability_gate",
        },
    )

    builder.add_conditional_edges(
        "external_structure_input",
        route_after_external_structure_input,
        {
            "formation": "formation_energy",
            "stability": "stability_screening",
            "end": END,
        },
    )

    builder.add_edge(
        "capability_gate",
        "router",
    )

    builder.add_edge(
        "router",
        "planner",
    )

    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "rag": "literature_evidence",
            "skip_rag": "skip_rag",
        },
    )

    builder.add_conditional_edges(
        "literature_evidence",
        route_after_literature_evidence,
        {
            "extract": "literature_assertion_extraction",
            "online_failure": "literature_online_failure",
        },
    )

    builder.add_edge("literature_online_failure", END)

    builder.add_edge(
        "literature_assertion_extraction",
        "literature_review",
    )

    builder.add_edge("literature_review", "literature_commit")

    builder.add_conditional_edges(
        "literature_commit",
        route_after_literature_commit,
        {
            "retry_online": "literature_retry_prepare",
            "continue": "literature_review_finalize",
        },
    )

    builder.add_edge("literature_retry_prepare", "literature_evidence")
    builder.add_edge("literature_review_finalize", "reviewed_rag")

    builder.add_edge(
        "reviewed_rag",
        "literature_summary",
    )

    builder.add_edge(
        "skip_rag",
        "literature_summary",
    )

    builder.add_conditional_edges(
        "literature_summary",
        route_after_literature_summary,
        {
            "candidate_design": "c_stage_preparation",
            "end": END,
        },
    )

    builder.add_edge(
        "c_stage_preparation",
        "candidate_generation",
    )

    builder.add_edge(
        "candidate_generation",
        "candidate_review",
    )

    builder.add_edge(
        "candidate_review",
        "c_stage_execution_review",
    )

    builder.add_conditional_edges(
        "c_stage_execution_review",
        route_after_c_stage_execution_review,
        {
            "structure": "structure_modeling",
            "end": END,
        },
    )

    builder.add_conditional_edges(
        "structure_modeling",
        route_after_structure_modeling,
        {
            "formation_energy": "formation_energy",
            "end": END,
        },
    )

    builder.add_conditional_edges(
        "formation_energy",
        route_after_formation_energy,
        {
            "bulk_dft": "bulk_dft_input_preview",
            "source_review": "formation_energy_source_review",
        },
    )

    builder.add_conditional_edges(
        "formation_energy_source_review",
        route_after_formation_energy_source_review,
        {
            "stability": "stability_screening",
            "end": END,
        },
    )

    builder.add_edge(
        "bulk_dft_input_preview",
        "bulk_dft_input_review",
    )

    builder.add_conditional_edges(
        "bulk_dft_input_review",
        route_after_bulk_dft_review,
        {
            "revise": "bulk_dft_revision_plan",
            "finalize": "bulk_dft_input_finalize",
        },
    )

    builder.add_edge(
        "bulk_dft_revision_plan",
        "bulk_dft_revision_apply",
    )

    builder.add_edge(
        "bulk_dft_revision_apply",
        "bulk_dft_input_review",
    )

    builder.add_edge(
        "bulk_dft_input_finalize",
        "dft_execution_options",
    )

    builder.add_conditional_edges(
        "stability_screening",
        route_after_stability_screening,
        {
            "review": "c7_dft_upgrade_review",
            "slab": "slab_generation",
            "end": END,
        },
    )

    builder.add_conditional_edges(
        "c7_dft_upgrade_review",
        route_after_c7_dft_upgrade_review,
        {
            "slab": "slab_generation",
            "end": END,
        },
    )

    builder.add_edge(
        "slab_generation",
        "slab_quality",
    )

    builder.add_edge(
        "slab_quality",
        "slab_review",
    )

    builder.add_edge(
        "slab_review",
        "dft_input_preview",
    )

    builder.add_edge(
        "dft_input_preview",
        "dft_input_review",
    )

    builder.add_conditional_edges(
        "dft_input_review",
        route_after_dft_input_review,
        {
            "revise": "dft_revision_plan",
            "finalize": "dft_input_finalize",
        },
    )

    builder.add_edge(
        "dft_revision_plan",
        "dft_revision_apply",
    )

    builder.add_edge(
        "dft_revision_apply",
        "dft_input_review",
    )

    builder.add_edge(
        "dft_input_finalize",
        "dft_execution_options",
    )

    builder.add_conditional_edges(
        "dft_execution_options",
        route_after_dft_execution_options,
        {
            "preflight": "dft_local_preflight",
            "end": END,
        },
    )

    builder.add_conditional_edges(
        "dft_local_preflight",
        route_after_dft_local_preflight,
        {
            "cluster_preflight": (
                "cluster_readonly_preflight"
            ),
            "end": END,
        },
    )

    builder.add_conditional_edges(
        "cluster_readonly_preflight",
        route_after_cluster_readonly_preflight,
        {
            "remote_plan": "remote_execution_plan",
            "end": END,
        },
    )

    builder.add_conditional_edges(
        "remote_execution_plan",
        route_after_remote_execution_plan,
        {
            "upload_review": "remote_upload_review",
            "end": END,
        },
    )

    builder.add_conditional_edges(
        "remote_upload_review",
        route_after_remote_upload_review,
        {
            "upload": "remote_upload",
            "end": END,
        },
    )

    builder.add_conditional_edges(
        "remote_upload",
        route_after_remote_upload,
        {
            "submission_review": (
                "remote_submission_review"
            ),
            "end": END,
        },
    )

    builder.add_conditional_edges(
        "remote_submission_review",
        route_after_remote_submission_review,
        {
            "submit": "remote_submission",
            "end": END,
        },
    )

    builder.add_edge(
        "remote_submission",
        "submission_record",
    )

    builder.add_edge(
        "submission_record",
        END,
    )

    return builder.compile(
        checkpointer=checkpointer or persistent_checkpointer()
    )


graph = build_graph()
