from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

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
)
from app.graph.routes import (
    route_after_adsorption_dft_review,
)
from app.graph.state import CatalystState


def build_adsorption_graph(checkpointer=None):
    """Build C12.1-C12.5 from relaxed CONTCAR to five files."""

    builder = StateGraph(CatalystState)

    for name, node in (
        (
            "adsorption_reaction_planning",
            adsorption_reaction_planning_node,
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
            adsorption_dft_finalize_node,
        ),
    ):
        builder.add_node(name, node)

    builder.add_edge(
        START,
        "adsorption_reaction_planning",
    )
    builder.add_edge(
        "adsorption_reaction_planning",
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
    builder.add_edge(
        "adsorption_dft_finalize",
        END,
    )

    return builder.compile(
        checkpointer=checkpointer or InMemorySaver()
    )


adsorption_graph = build_adsorption_graph()
