from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.domain.formation_energy_backfill import FormationEnergyBackfillService


def show(title: str, value: Any) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def calculate(link_path: str, expected_job_id: str | None = None) -> dict[str, Any]:
    if expected_job_id:
        manifest = json.loads(Path(link_path).read_text(encoding="utf-8"))
        if str(manifest.get("alloy_slurm_job_id", "")) != expected_job_id:
            raise ValueError("--job-id does not match the job-link manifest")
    return FormationEnergyBackfillService().calculate(link_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate Bulk DFT formation energy and run C7 screening.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    command = subparsers.add_parser("calculate")
    command.add_argument("--job-id", help="Expected numeric Slurm job ID")
    command.add_argument("--link", required=True, help="C11.7 job-link JSON path")
    args = parser.parse_args()
    if args.job_id and not args.job_id.isdigit():
        raise ValueError("--job-id must contain digits only")
    result = calculate(args.link, args.job_id)
    show("Reference validation", {"status": "passed", "data_version": result["reference_data_version"], "terms": result["reference_terms"]})
    show("Bulk DFT evidence", {"slurm_job_id": result["slurm_job_id"], "energy_field": result["alloy_energy_field"], "alloy_energy_ev": result["alloy_energy_ev"], "calculation_method": result["calculation_method"], "static_single_point_used": result["static_single_point_used"]})
    show("Formation-energy result", {"status": result["status"], "reference_total_energy_ev": result["reference_total_energy_ev"], "formation_energy": result["formation_energy"], "unit": result["formation_energy_unit"], "result_path": result["result_path"]})
    show("C7 screening result", {"formation_energy_pass": result["c7_formation_energy_pass"], "stability_decision": result["c7_stability_decision"], "eligible_for_slab": result["eligible_for_slab"], "c7_result_path": result["c7_result_path"]})


if __name__ == "__main__":
    main()
