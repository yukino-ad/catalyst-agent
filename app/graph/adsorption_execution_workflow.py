from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    adsorption_dft_execution_options_node,
    cluster_readonly_preflight_node,
    dft_local_preflight_node,
    remote_execution_plan_node,
    remote_submission_node,
    remote_submission_review_node,
    remote_upload_node,
    remote_upload_review_node,
    submission_record_node,
)
from app.graph.routes import (
    route_after_cluster_readonly_preflight,
    route_after_dft_execution_options,
    route_after_dft_local_preflight,
    route_after_remote_execution_plan,
    route_after_remote_submission_review,
    route_after_remote_upload,
    route_after_remote_upload_review,
)
from app.graph.state import CatalystState


def build_adsorption_execution_graph(checkpointer=None):
    """Build the reviewed C12.6 upload and submission graph."""

    builder = StateGraph(CatalystState)
    for name, node in (
        (
            "adsorption_dft_execution_options",
            adsorption_dft_execution_options_node,
        ),
        ("dft_local_preflight", dft_local_preflight_node),
        (
            "cluster_readonly_preflight",
            cluster_readonly_preflight_node,
        ),
        (
            "remote_execution_plan",
            remote_execution_plan_node,
        ),
        ("remote_upload_review", remote_upload_review_node),
        ("remote_upload", remote_upload_node),
        (
            "remote_submission_review",
            remote_submission_review_node,
        ),
        ("remote_submission", remote_submission_node),
        ("submission_record", submission_record_node),
    ):
        builder.add_node(name, node)

    builder.add_edge(
        START,
        "adsorption_dft_execution_options",
    )
    builder.add_conditional_edges(
        "adsorption_dft_execution_options",
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
    builder.add_edge("submission_record", END)

    return builder.compile(
        checkpointer=checkpointer or InMemorySaver()
    )


adsorption_execution_graph = (
    build_adsorption_execution_graph()
)
