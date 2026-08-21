from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    adsorption_energy_calculation_node,
    adsorption_energy_review_node,
)
from app.graph.state import CatalystState


def build_adsorption_energy_graph(checkpointer=None):
    """Build the C12.7 calculation and human-review graph."""

    builder = StateGraph(CatalystState)
    builder.add_node(
        "adsorption_energy_calculation",
        adsorption_energy_calculation_node,
    )
    builder.add_node(
        "adsorption_energy_review",
        adsorption_energy_review_node,
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


adsorption_energy_graph = build_adsorption_energy_graph()
