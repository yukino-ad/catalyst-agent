from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from langgraph.types import Command

from app.graph.adsorption_energy_workflow import (
    adsorption_energy_graph,
)
from app.graph.cli import (
    collect_adsorption_energy_review,
)


def show(title: str, value: Any) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def load_state(path: str) -> dict[str, Any]:
    target = Path(path).resolve()
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("C12.7 input JSON must be an object")

    required = {
        "adsorption_parsed_results",
        "clean_slab_energies",
        "reference_energies",
    }
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(
            "C12.7 input is missing: " + ", ".join(missing)
        )

    if not isinstance(value["adsorption_parsed_results"], list):
        raise TypeError("adsorption_parsed_results must be a list")
    if not isinstance(value["clean_slab_energies"], dict):
        raise TypeError("clean_slab_energies must be an object")
    if not isinstance(value["reference_energies"], dict):
        raise TypeError("reference_energies must be an object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calculate and review simplified C12.7 adsorption energy"
    )
    parser.add_argument(
        "state_json",
        help=(
            "JSON containing adsorption_parsed_results, "
            "clean_slab_energies, and reference_energies"
        ),
    )
    parser.add_argument("--thread-id", default="")
    args = parser.parse_args()

    state = load_state(args.state_json)
    thread_id = args.thread_id.strip() or (
        f"adsorption-energy-{uuid.uuid4().hex[:12]}"
    )
    config = {"configurable": {"thread_id": thread_id}}
    result = adsorption_energy_graph.invoke(
        {
            **state,
            "errors": state.get("errors", []),
        },
        config=config,
    )

    while "__interrupt__" in result:
        request = result["__interrupt__"][0].value
        if request.get("type") != "adsorption_energy_review_required":
            raise RuntimeError(
                "Unsupported C12.7 interrupt: "
                + str(request.get("type"))
            )
        decision = collect_adsorption_energy_review(request)
        result = adsorption_energy_graph.invoke(
            Command(resume=decision),
            config=config,
        )

    show(
        "adsorption_energy_calculation",
        result.get("adsorption_energy_calculation", {}),
    )
    show(
        "adsorption_energy_review",
        result.get("adsorption_energy_review", {}),
    )
    show(
        "final",
        {
            "status": result.get("status"),
            "approved_count": len(
                result.get("approved_adsorption_energies", [])
            ),
        },
    )


if __name__ == "__main__":
    main()
