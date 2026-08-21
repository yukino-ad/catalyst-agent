from __future__ import annotations

from typing import Any


class SlabReviewGate:
    """Validate human decisions for quality-approved slabs."""

    ACTIONS = ("approve", "reject", "defer")

    def __init__(self, max_approved: int = 3) -> None:
        self.max_approved = max_approved

    def review(
        self,
        slabs: list[dict[str, Any]],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(slabs, list):
            raise TypeError("slabs must be a list")
        if not isinstance(decision, dict):
            raise TypeError("decision must be a dictionary")

        prepared: dict[str, dict[str, Any]] = {}

        for slab in slabs:
            slab_id = str(
                slab.get("slab_id", "")
            ).strip()

            if not slab_id:
                raise ValueError(
                    "Every slab requires slab_id"
                )
            if not slab.get(
                "eligible_for_dft_review",
                False,
            ):
                raise ValueError(
                    f"{slab_id} did not pass C9 quality inspection"
                )
            prepared[slab_id] = dict(slab)

        normalized = {
            action: self._ids(
                decision.get(action, [])
            )
            for action in self.ACTIONS
        }

        owners: dict[str, list[str]] = {}
        for action, slab_ids in normalized.items():
            for slab_id in slab_ids:
                owners.setdefault(
                    slab_id,
                    [],
                ).append(action)

        conflicts = {
            slab_id: actions
            for slab_id, actions in owners.items()
            if len(actions) > 1
        }
        if conflicts:
            raise ValueError(
                "A slab cannot have multiple decisions: "
                + str(conflicts)
            )

        classified = set().union(
            *(
                set(values)
                for values in normalized.values()
            )
        )
        unknown = sorted(
            classified - set(prepared)
        )
        if unknown:
            raise ValueError(
                "Unknown slab IDs: "
                + ", ".join(unknown)
            )

        if (
            len(normalized["approve"])
            > self.max_approved
        ):
            raise ValueError(
                f"At most {self.max_approved} slabs "
                "may be approved"
            )

        unclassified = [
            slab_id
            for slab_id in prepared
            if slab_id not in classified
        ]
        normalized["defer"] = list(dict.fromkeys([
            *normalized["defer"],
            *unclassified,
        ]))

        approved = self._with_status(
            prepared,
            normalized["approve"],
            "approved_for_dft",
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
            "schema_version": "c9.0",
            "stage": "c9_review",
            "status": "slab_review_completed",
            "decision": {
                **normalized,
                "note": str(
                    decision.get("note", "") or ""
                ).strip(),
            },
            "reviewed_count": len(slabs),
            "approved_count": len(approved),
            "rejected_count": len(rejected),
            "deferred_count": len(deferred),
            "approved": approved,
            "rejected": rejected,
            "deferred": deferred,
            "approved_for_dft": bool(approved),
            "requires_human_review": False,
            "next_stage": "dft_input_preparation",
        }

    @staticmethod
    def _ids(values: Any) -> list[str]:
        if values is None:
            return []
        if isinstance(values, str):
            values = values.split(",")
        if not isinstance(values, list):
            raise TypeError(
                "Review decisions must be lists "
                "or comma-separated strings"
            )
        return list(dict.fromkeys(
            str(value).strip()
            for value in values
            if str(value).strip()
        ))

    @staticmethod
    def _with_status(
        prepared: dict[str, dict[str, Any]],
        slab_ids: list[str],
        status: str,
    ) -> list[dict[str, Any]]:
        results = []

        for slab_id in slab_ids:
            slab = dict(prepared[slab_id])
            slab["slab_review_status"] = status
            results.append(slab)

        return results