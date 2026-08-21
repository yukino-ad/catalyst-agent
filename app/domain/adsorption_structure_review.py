from __future__ import annotations

from typing import Any


class AdsorptionStructureReviewGate:
    """Validate human decisions for C12.4 structures."""

    ACTIONS = (
        "approve",
        "reject",
        "defer",
    )

    def __init__(
        self,
        max_approved: int = 15,
    ) -> None:
        self.max_approved = max_approved

    def review(
        self,
        structures: list[dict[str, Any]],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(structures, list):
            raise TypeError(
                "structures must be a list"
            )

        if not isinstance(decision, dict):
            raise TypeError(
                "decision must be a dictionary"
            )

        prepared = {}

        for structure in structures:
            structure_id = str(
                structure.get(
                    "adsorption_structure_id",
                    "",
                )
            ).strip()

            if not structure_id:
                raise ValueError(
                    "Every structure requires "
                    "adsorption_structure_id"
                )

            if not structure.get(
                "eligible_for_adsorption_review",
                False,
            ):
                raise ValueError(
                    f"{structure_id} did not pass "
                    "C12.4 quality inspection"
                )

            if (
                structure.get(
                    "adsorbate_instance_count"
                )
                != 1
                or structure.get(
                    "coadsorption"
                ) is not False
            ):
                raise ValueError(
                    f"{structure_id} violates the "
                    "single-adsorbate rule"
                )

            prepared[structure_id] = dict(
                structure
            )

        normalized = {
            action: self._ids(
                decision.get(action, [])
            )
            for action in self.ACTIONS
        }

        owners = {}

        for action, identifiers in (
            normalized.items()
        ):
            for identifier in identifiers:
                owners.setdefault(
                    identifier,
                    [],
                ).append(action)

        conflicts = {
            identifier: actions
            for identifier, actions
            in owners.items()
            if len(actions) > 1
        }

        if conflicts:
            raise ValueError(
                "A structure cannot have "
                "multiple decisions: "
                + str(conflicts)
            )

        classified = set().union(
            *(
                set(values)
                for values
                in normalized.values()
            )
        )

        unknown = sorted(
            classified - set(prepared)
        )

        if unknown:
            raise ValueError(
                "Unknown adsorption structures: "
                + ", ".join(unknown)
            )

        if (
            len(normalized["approve"])
            > self.max_approved
        ):
            raise ValueError(
                f"At most {self.max_approved} "
                "structures may be approved"
            )

        unclassified = [
            identifier
            for identifier in prepared
            if identifier not in classified
        ]

        normalized["defer"] = list(
            dict.fromkeys([
                *normalized["defer"],
                *unclassified,
            ])
        )

        approved = self._with_status(
            prepared,
            normalized["approve"],
            "approved_for_adsorption_dft",
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
            "schema_version": "c12.4",
            "stage": "c12.4_review",
            "status": (
                "adsorption_structure_review_completed"
            ),
            "decision": {
                **normalized,
                "note": str(
                    decision.get("note", "")
                    or ""
                ).strip(),
            },
            "reviewed_count": len(structures),
            "approved_count": len(approved),
            "rejected_count": len(rejected),
            "deferred_count": len(deferred),
            "approved": approved,
            "rejected": rejected,
            "deferred": deferred,
            "approved_for_adsorption_dft": bool(
                approved
            ),
            "maximum_approved": (
                self.max_approved
            ),
            "next_stage": (
                "c12.5_adsorption_dft_preview"
            ),
        }

    @staticmethod
    def _ids(
        values: Any,
    ) -> list[str]:
        if values is None:
            return []

        if isinstance(values, str):
            values = values.split(",")

        if not isinstance(values, list):
            raise TypeError(
                "Review decisions must be lists"
            )

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
            value = dict(
                prepared[identifier]
            )
            value[
                "adsorption_review_status"
            ] = status
            results.append(value)

        return results