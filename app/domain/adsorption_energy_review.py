from __future__ import annotations

from typing import Any


class AdsorptionEnergyReviewGate:
    """Review calculated C12.7 adsorption energies."""

    def review(
        self,
        calculations: list[dict[str, Any]],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(calculations, list):
            raise TypeError("calculations must be a list")
        if not isinstance(decision, dict):
            raise TypeError("decision must be a dictionary")

        prepared: dict[str, dict[str, Any]] = {}
        for item in calculations:
            if not isinstance(item, dict):
                raise TypeError(
                    "Every adsorption-energy result must be a dictionary"
                )
            identifier = str(
                item.get("adsorption_energy_id", "")
            ).strip()
            if not identifier:
                raise ValueError(
                    "Every result requires adsorption_energy_id"
                )
            if identifier in prepared:
                raise ValueError(
                    f"Duplicate adsorption_energy_id: {identifier}"
                )
            if item.get("status") != "calculated_requires_review":
                raise ValueError(
                    f"{identifier} is not ready for review"
                )
            prepared[identifier] = dict(item)

        normalized = {
            action: self._ids(decision.get(action, []))
            for action in ("approve", "reject", "defer")
        }
        owners: dict[str, list[str]] = {}
        for action, identifiers in normalized.items():
            for identifier in identifiers:
                owners.setdefault(identifier, []).append(action)

        conflicts = {
            identifier: actions
            for identifier, actions in owners.items()
            if len(actions) > 1
        }
        if conflicts:
            raise ValueError(
                "An adsorption energy cannot have multiple decisions: "
                + str(conflicts)
            )

        classified = set().union(
            *(set(values) for values in normalized.values())
        )
        unknown = sorted(classified - set(prepared))
        if unknown:
            raise ValueError(
                "Unknown adsorption energy IDs: "
                + ", ".join(unknown)
            )

        normalized["defer"] = list(dict.fromkeys([
            *normalized["defer"],
            *(
                identifier
                for identifier in prepared
                if identifier not in classified
            ),
        ]))

        approved = self._with_status(
            prepared,
            normalized["approve"],
            "approved",
        )
        rejected = self._with_status(
            prepared,
            normalized["reject"],
            "rejected",
        )
        deferred = self._with_status(
            prepared,
            normalized["defer"],
            "deferred",
        )

        return {
            "schema_version": "c12.7",
            "stage": "c12.7_adsorption_energy_review",
            "status": "adsorption_energy_review_completed",
            "decision": {
                **normalized,
                "note": str(decision.get("note", "") or "").strip(),
            },
            "reviewed_count": len(calculations),
            "approved_count": len(approved),
            "rejected_count": len(rejected),
            "deferred_count": len(deferred),
            "approved": approved,
            "rejected": rejected,
            "deferred": deferred,
            "requires_further_validation": bool(approved),
            "next_stage": "c12.8_adsorption_result_summary",
        }

    @staticmethod
    def _ids(values: Any) -> list[str]:
        if values is None:
            return []
        if isinstance(values, str):
            values = values.split(",")
        if not isinstance(values, list):
            raise TypeError("Review IDs must be a list")
        return list(dict.fromkeys(
            str(value).strip()
            for value in values
            if str(value).strip()
        ))

    @staticmethod
    def _with_status(
        prepared: dict[str, dict[str, Any]],
        identifiers: list[str],
        status: str,
    ) -> list[dict[str, Any]]:
        results = []
        for identifier in identifiers:
            value = dict(prepared[identifier])
            value["adsorption_energy_review_status"] = status
            results.append(value)
        return results
