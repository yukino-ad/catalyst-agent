from __future__ import annotations

from typing import Any

from app.domain.dft_input_revision import DFTInputRevisionService


class BulkDFTInputRevisionService(DFTInputRevisionService):
    """C6D facade over the validated C10 revision engine."""

    def parse_requests(
        self,
        revision_requests: dict[str, str],
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        result = super().parse_requests(revision_requests, preview)
        result.update({
            "schema_version": "c6d-revision-v1",
            "status": "bulk_dft_revision_plan_ready",
        })
        return result

    def apply(
        self,
        preview: dict[str, Any],
        plan: dict[str, Any],
        revision_count: int = 0,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        result = super().apply(
            preview, plan, revision_count, history
        )
        result["preview"]["schema_version"] = "c6d.1"
        result["validation"].update({
            "schema_version": "c6d-revision-v1",
            "status": "bulk_dft_revision_accepted",
        })
        return result
