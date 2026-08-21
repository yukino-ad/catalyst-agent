from __future__ import annotations

import json
import urllib.error
from typing import Any

from tools.literature.crossref_client import (
    CrossrefClient,
    CrossrefRateLimitError,
)
from tools.literature.retry_support import paper_identities
from tools.literature.schemas import PaperRecord


REACTION_TERMS = {
    "CO2RR": "carbon dioxide electrochemical reduction",
    "HER": "hydrogen evolution reaction electrocatalysis",
    "OER": "oxygen evolution reaction electrocatalysis",
    "ORR": "oxygen reduction reaction electrocatalysis",
    "NRR": "nitrogen reduction reaction electrocatalysis",
}

PRODUCT_TERMS = {
    "CO": "carbon monoxide",
    "HCOOH": "formic acid formate",
    "CH4": "methane",
    "C2H4": "ethylene",
    "NH3": "ammonia",
    "H2": "hydrogen",
    "O2": "oxygen",
}


class OnlineLiteratureRetriever:
    """Run B4 Crossref searches without writing to the repository."""

    def __init__(self, client: CrossrefClient | None = None) -> None:
        self.client = client or CrossrefClient()

    def retrieve(
        self,
        policy_result: dict[str, Any],
        question: str,
        task_analysis: dict[str, Any] | None = None,
        keywords: list[str] | None = None,
        per_page: int = 20,
        mailto: str = "",
        search_queries: list[str] | None = None,
        excluded_identities: set[str] | None = None,
    ) -> dict[str, Any]:
        """Run one or more queries and remove prior B6 rejections."""

        if not isinstance(policy_result, dict):
            raise TypeError("policy_result must be a dictionary")
        if not question.strip():
            raise ValueError("question must not be empty")
        if not 1 <= per_page <= 100:
            raise ValueError("per_page must be between 1 and 100")

        decision = str(policy_result.get("decision", ""))
        if not policy_result.get("use_online_search", False):
            return {
                "status": "skipped",
                "decision": decision,
                "search_query": "",
                "search_queries": [],
                "candidate_count": 0,
                "candidates": [],
                "warnings": [],
                "reason": (
                    "Local evidence satisfied the configured threshold; "
                    "online retrieval was not needed."
                ),
            }

        primary_query = self.build_query(
            question=question,
            task_analysis=task_analysis or {},
            keywords=keywords or [],
        )
        queries = [
            str(value).strip()
            for value in (search_queries or [primary_query])
            if str(value).strip()
        ]
        queries = list(dict.fromkeys(queries)) or [primary_query]
        excluded = set(excluded_identities or set())

        records: list[PaperRecord] = []
        failures: list[str] = []
        for index, query in enumerate(queries, 1):
            print(
                f"[B4] Crossref query {index}/{len(queries)}: {query}",
                flush=True,
            )
            try:
                query_records = self.client.search(
                    query=query,
                    per_page=per_page,
                    mailto=mailto,
                )
                records.extend(query_records)
                print(
                    f"[B4] Query {index}/{len(queries)} completed: "
                    f"{len(query_records)} records.",
                    flush=True,
                )
            except CrossrefRateLimitError as error:
                failures.append(f"{query}: {error}")
                print(
                    "[B4] Crossref imposed a long rate limit; "
                    "remaining queries are cancelled.",
                    flush=True,
                )
                break
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                OSError,
                json.JSONDecodeError,
            ) as error:
                failures.append(f"{query}: {error}")
                print(
                    f"[B4] Query {index}/{len(queries)} failed: {error}",
                    flush=True,
                )

        if failures and not records:
            print("[B4] All Crossref queries failed; stopping B-stage.", flush=True)
            return {
                "status": "online_failed",
                "decision": decision,
                "search_query": primary_query,
                "search_queries": queries,
                "candidate_count": 0,
                "candidates": [],
                "warnings": failures,
            }

        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        excluded_count = 0
        for record in records:
            candidate = self._temporary_candidate(
                record, rank=len(candidates) + 1
            )
            identities = paper_identities(candidate)
            if identities & excluded:
                excluded_count += 1
                continue
            identity = sorted(identities)[0] if identities else str(candidate)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(candidate)

        return {
            "status": "completed" if candidates else "completed_no_results",
            "decision": decision,
            "search_query": primary_query,
            "search_queries": queries,
            "provider": "crossref",
            "query_count": len(queries),
            "candidate_count": len(candidates),
            "candidates": candidates,
            "excluded_previous_rejections": excluded_count,
            "metadata_verified_count": sum(
                int(bool(candidate.get("metadata_verified")))
                for candidate in candidates
            ),
            "claim_evidence_available_count": sum(
                int(bool(candidate.get("claim_evidence_available")))
                for candidate in candidates
            ),
            "warnings": failures if candidates else [
                *failures, "Crossref returned no new matching papers."
            ],
        }

    @staticmethod
    def build_query(
        question: str,
        task_analysis: dict[str, Any],
        keywords: list[str],
    ) -> str:
        parts: list[str] = []
        reaction = str(task_analysis.get("reaction_family", "") or "").upper()
        combined_text = " ".join([question, *keywords]).lower()

        if "high entropy" in combined_text or "高熵" in combined_text:
            parts.append("high entropy alloy catalyst")
        reaction_term = REACTION_TERMS.get(reaction)
        if reaction_term:
            parts.append(reaction_term)

        target_product = str(
            task_analysis.get("target_product", "") or ""
        ).strip().upper()
        product_term = PRODUCT_TERMS.get(target_product)
        if product_term:
            parts.append(product_term)

        for keyword in keywords:
            value = str(keyword).strip()
            if value and value.isascii() and value.lower() not in " ".join(parts).lower():
                parts.append(value)
            if len(parts) >= 7:
                break
        if not parts:
            parts.append(question.strip())
        return " ".join(parts)[:500]

    @staticmethod
    def _temporary_candidate(record: PaperRecord, rank: int) -> dict[str, Any]:
        candidate = record.to_dict()
        candidate.update({
            "retrieval_origin": "online",
            "online_rank": rank,
            "review_status": "pending_review",
            "stored_in_repository": False,
            "metadata_verified": candidate.get("metadata_verified", False) is True,
            "metadata_provider": str(
                candidate.get("metadata_provider", "") or ""
            ),
            "claim_evidence_available": (
                candidate.get("claim_evidence_available", False) is True
                and bool(candidate.get("abstract"))
            ),
        })
        return candidate
