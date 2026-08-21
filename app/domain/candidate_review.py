from __future__ import annotations

from typing import Any


class CandidateReviewGate:
    """Validate human decisions for ranked material candidates."""

    ACTIONS = ("select", "reject", "defer")

    def __init__(self, max_selected: int = 3) -> None:
        if isinstance(max_selected, bool) or not isinstance(
            max_selected, int
        ) or max_selected <= 0:
            raise ValueError("max_selected must be a positive integer")
        self.max_selected = max_selected

    def review(
        self,
        candidates: list[dict[str, Any]],
        decision: dict[str, Any],
        total_candidate_count: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(candidates, list):
            raise TypeError("candidates must be a list")
        if not isinstance(decision, dict):
            raise TypeError("decision must be a dictionary")

        prepared = self._prepare(candidates)
        known_ids = set(prepared)
        normalized = {
            action: self._ids(decision.get(action, []), action)
            for action in self.ACTIONS
        }
        self._check_conflicts(normalized)

        classified = set().union(
            *(set(values) for values in normalized.values())
        )
        unknown = sorted(classified - known_ids)
        if unknown:
            raise ValueError(
                "Unknown candidate IDs: " + ", ".join(unknown)
            )

        if len(normalized["select"]) > self.max_selected:
            raise ValueError(
                f"At most {self.max_selected} candidates may be selected"
            )

        unclassified = [
            candidate_id
            for candidate_id in prepared
            if candidate_id not in classified
        ]
        normalized["defer"] = self._unique(
            normalized["defer"] + unclassified
        )

        selected = self._with_status(
            prepared, normalized["select"], "selected"
        )
        rejected = self._with_status(
            prepared, normalized["reject"], "rejected"
        )
        deferred = self._with_status(
            prepared, normalized["defer"], "deferred"
        )

        total = (
            len(candidates)
            if total_candidate_count is None
            else int(total_candidate_count)
        )
        if total < len(candidates):
            raise ValueError(
                "total_candidate_count cannot be smaller "
                "than reviewed candidate count"
            )

        return {
            "schema_version": "c4.1",
            "status": "candidate_review_completed",
            "decision": {
                **normalized,
                "note": str(decision.get("note", "") or "").strip(),
            },
            "total_candidate_count": total,
            "reviewed_candidate_count": len(candidates),
            "unreviewed_candidate_count": total - len(candidates),
            "selected_count": len(selected),
            "rejected_count": len(rejected),
            "deferred_count": len(deferred),
            "selected": selected,
            "rejected": rejected,
            "deferred": deferred,
            "unclassified_moved_to_defer": unclassified,
            "max_selected": self.max_selected,
            "ready_for_structure_modeling": bool(selected),
            "requires_human_review": False,
            "warning": (
                "Selection permits later modeling; it does not prove "
                "catalytic activity or structural stability."
            ),
        }

    @staticmethod
    def _prepare(candidates):
        prepared = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise TypeError("Every candidate must be a dictionary")
            candidate_id = str(
                candidate.get("candidate_id", "") or ""
            ).strip()
            if not candidate_id:
                raise ValueError("Every candidate requires candidate_id")
            if candidate_id in prepared:
                raise ValueError(f"Duplicate candidate_id: {candidate_id}")
            prepared[candidate_id] = dict(candidate)
        return prepared

    @staticmethod
    def _ids(values, action):
        if values is None:
            return []
        if isinstance(values, str):
            values = values.replace("，", ",").split(",")
        if not isinstance(values, list):
            raise TypeError(
                f"decision.{action} must be a list or CSV string"
            )
        return CandidateReviewGate._unique([
            str(value).strip() for value in values
            if str(value).strip()
        ])

    @staticmethod
    def _check_conflicts(decision):
        owners = {}
        for action, candidate_ids in decision.items():
            for candidate_id in candidate_ids:
                owners.setdefault(candidate_id, []).append(action)
        conflicts = {
            key: value for key, value in owners.items()
            if len(value) > 1
        }
        if conflicts:
            raise ValueError(
                "A candidate cannot have multiple decisions: "
                + str(conflicts)
            )

    @staticmethod
    def _with_status(prepared, candidate_ids, status):
        results = []
        for candidate_id in candidate_ids:
            candidate = dict(prepared[candidate_id])
            candidate["candidate_review_status"] = status
            results.append(candidate)
        return results

    @staticmethod
    def _unique(values):
        return list(dict.fromkeys(values))