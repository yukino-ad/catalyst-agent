from __future__ import annotations

from typing import Any

from tools.literature.evidence_quality import EvidenceQualityEvaluator
from tools.literature.repository import LiteratureRepository


class LocalLiteratureRetriever:
    """从本地 SQLite 召回、评价并重排论文。"""

    MAX_QUALITY_SCORE = 100

    def __init__(
        self,
        repository: LiteratureRepository | None = None,
        quality_evaluator: EvidenceQualityEvaluator | None = None,
    ) -> None:
        self.repository = repository or LiteratureRepository()
        self.quality_evaluator = (
            quality_evaluator
            or EvidenceQualityEvaluator()
        )

    def retrieve(
        self,
        query: str,
        keywords: list[str] | None = None,
        task_analysis: dict[str, Any] | None = None,
        recall_count: int = 20,
        final_count: int = 5,
    ) -> dict[str, Any]:
        """召回较多论文，质量评价后只返回少量证据。"""

        query = query.strip()
        keywords = keywords or []
        task_analysis = task_analysis or {}

        if not query:
            raise ValueError("本地文献检索问题不能为空。")

        if recall_count <= 0:
            raise ValueError("recall_count 必须大于 0。")

        if final_count <= 0:
            raise ValueError("final_count 必须大于 0。")

        if final_count > recall_count:
            raise ValueError(
                "final_count 不能大于 recall_count。"
            )

        combined_query = self._combined_query(
            query,
            keywords,
        )

        recalled = self.repository.search(
            query=combined_query,
            top_k=recall_count,
        )

        evaluated = self.quality_evaluator.evaluate_many(
            papers=recalled,
            task_analysis=task_analysis,
        )

        ranked = self._rank(evaluated)

        # D 级论文保留在 rejected 中，不作为最终证据。
        eligible = [
            paper
            for paper in ranked
            if paper["evidence_quality"]["quality_level"]
            != "D"
        ]

        selected = eligible[:final_count]

        for index, paper in enumerate(
            selected,
            start=1,
        ):
            paper["local_rank"] = index
            paper["evidence_id"] = f"E{index}"

        rejected = [
            paper
            for paper in ranked
            if paper["evidence_quality"]["quality_level"]
            == "D"
        ]

        return {
            "query": query,
            "combined_query": combined_query,
            "recall_count_requested": recall_count,
            "local_recall_count": len(recalled),
            "eligible_count": len(eligible),
            "selected_count": len(selected),
            "selected": selected,
            "rejected": rejected,
            "ranking_method": (
                "0.60 * lexical_relevance + "
                "0.40 * evidence_quality"
            ),
        }

    def _rank(
        self,
        papers: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """综合词法相关性与 B1 证据质量排序。"""

        if not papers:
            return []

        maximum_lexical_score = max(
            float(paper.get("score", 0))
            for paper in papers
        )

        ranked: list[dict[str, Any]] = []

        for paper in papers:
            item = dict(paper)

            raw_lexical_score = float(
                item.get("score", 0)
            )

            if maximum_lexical_score > 0:
                lexical_normalized = (
                    raw_lexical_score
                    / maximum_lexical_score
                )
            else:
                lexical_normalized = 0.0

            quality_score = float(
                item["evidence_quality"].get(
                    "quality_score",
                    0,
                )
            )

            quality_normalized = (
                quality_score
                / self.MAX_QUALITY_SCORE
            )

            ranking_score = (
                0.60 * lexical_normalized
                + 0.40 * quality_normalized
            )

            item["retrieval_scores"] = {
                "lexical_raw": round(
                    raw_lexical_score,
                    6,
                ),
                "lexical_normalized": round(
                    lexical_normalized,
                    6,
                ),
                "quality_normalized": round(
                    quality_normalized,
                    6,
                ),
                "combined": round(
                    ranking_score,
                    6,
                ),
            }

            ranked.append(item)

        ranked.sort(
            key=lambda paper: (
                -paper["retrieval_scores"]["combined"],
                -paper["evidence_quality"]["quality_score"],
                -(paper.get("year") or 0),
                paper.get("title", ""),
            )
        )

        return ranked

    @staticmethod
    def _combined_query(
        query: str,
        keywords: list[str],
    ) -> str:
        """合并用户问题与 Planner 检索词，并保持顺序。"""

        parts: list[str] = []

        for value in [query, *keywords]:
            text = str(value).strip()

            if text and text not in parts:
                parts.append(text)

        return " ".join(parts)
