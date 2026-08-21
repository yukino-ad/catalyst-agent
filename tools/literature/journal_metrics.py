from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any


class JournalMetricRegistry:
    """Attach versioned journal metrics without guessing missing values."""

    FIELDNAMES = (
        "journal_name", "issn", "openalex_source_id", "metric_name",
        "metric_value", "metric_year", "source", "verified_at",
    )

    def __init__(self, path: str | Path = "database/literature/journal_metrics.csv") -> None:
        value = Path(path)
        if not value.is_absolute():
            value = Path(__file__).resolve().parents[2] / value
        self.path = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with self.path.open("w", newline="", encoding="utf-8-sig") as stream:
                csv.DictWriter(stream, fieldnames=self.FIELDNAMES).writeheader()

    def enrich(self, paper: dict[str, Any]) -> dict[str, Any]:
        result = dict(paper)
        if result.get("journal_impact_factor") is not None:
            return result
        match = self.lookup(result)
        if match:
            result.update({
                "journal_impact_factor": float(match["metric_value"]),
                "journal_metric_year": int(match["metric_year"]),
                "journal_metric_source": match["source"],
                "journal_metric_name": match["metric_name"],
                "journal_metric_match": match["match_method"],
            })
        return result

    def lookup(self, paper: dict[str, Any]) -> dict[str, str] | None:
        if not self.path.exists():
            return None
        with self.path.open("r", newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        paper_issns = {
            self._normalize_issn(value)
            for value in paper.get("issns", [])
            if self._normalize_issn(value)
        }
        if paper.get("issn_l"):
            paper_issns.add(self._normalize_issn(paper["issn_l"]))
        source_id = str(paper.get("openalex_source_id", "") or "").strip().lower()
        journal = self._normalize_name(paper.get("journal", ""))
        for method in ("issn", "openalex_source_id", "journal_name"):
            for row in rows:
                if not row.get("metric_value") or not row.get("metric_year") or not row.get("source"):
                    continue
                matched = (
                    method == "issn" and self._normalize_issn(row.get("issn", "")) in paper_issns
                    or method == "openalex_source_id" and source_id and str(row.get("openalex_source_id", "")).strip().lower() == source_id
                    or method == "journal_name" and journal and self._normalize_name(row.get("journal_name", "")) == journal
                )
                if matched:
                    return {**row, "match_method": method}
        return None

    @staticmethod
    def _normalize_issn(value: Any) -> str:
        return re.sub(r"[^0-9x]", "", str(value or "").lower())

    @staticmethod
    def _normalize_name(value: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


__all__ = ["JournalMetricRegistry"]
