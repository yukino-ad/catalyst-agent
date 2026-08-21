from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


def build_report(result: dict[str, Any]) -> str:
    """Create a Markdown report from CatalystAgent.run()."""
    plan = result["plan"]
    lines = [
        "# Catalyst Agent Report",
        "",
        f"Generated at: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "## Research target",
        "",
        f"- Question: {plan['question']}",
        f"- Reaction: {plan['reaction']}",
        f"- Product: {plan['product']}",
        "",
        "## Candidates",
        "",
    ]
    for candidate in result["candidates"]:
        lines.append(
            f"- {candidate['formula']}: score={candidate['score']}, "
            f"composition={candidate['composition']}"
        )

    structure = result.get("structure_result")
    lines.extend(("", "## Generated structures", ""))
    if not structure:
        lines.append("- Structure generation was disabled.")
    else:
        for item in structure["results"]:
            lines.extend(
                (
                    f"- {item['formula']}",
                    f"  - CIF: {item['cif_path']}",
                    f"  - POSCAR: {item['poscar_path']}",
                )
            )
            if "formation_energy_per_atom" in item:
                lines.append(
                    f"  - CGCNN formation energy: {item['formation_energy_per_atom']:.6f} "
                    f"{item['formation_energy_unit']}"
                )
    return "\n".join(lines) + "\n"


def save_report(report: str, output_dir: str | Path = "data/outputs") -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"agent_report_{datetime.now():%Y%m%d_%H%M%S}.md"
    path.write_text(report, encoding="utf-8")
    return path.resolve()
