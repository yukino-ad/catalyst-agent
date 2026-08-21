from __future__ import annotations

import html
import json
import math
import re
from datetime import datetime
from typing import Any

from tools.literature.evidence_quality import (
    EvidenceQualityEvaluator,
)


class LiteratureEvidenceMerger:
    """
    合并 B2 本地文献和 B4 在线候选文献。

    本类负责：
    1. 汇总本地与在线候选；
    2. 使用 DOI、OpenAlex ID、规范化标题去重；
    3. 识别预印本和正式期刊版本；
    4. 合并重复记录中的互补元数据；
    5. 使用 B1 标准重新评价；
    6. 按相关性、证据质量和时效性重排。

    本类不会：
    1. 访问互联网；
    2. 调用 LLM；
    3. 修改正式文献数据库；
    4. 判断论文的科学结论一定正确。
    """

    MAX_QUALITY_SCORE = 100

    PREPRINT_MARKERS = (
        "arxiv",
        "chemrxiv",
        "biorxiv",
        "medrxiv",
        "preprint",
        "ssrn",
        "research square",
    )

    REACTION_EXPANSIONS = {
        "CO2RR": (
            "CO2RR",
            "CO2 reduction",
            "carbon dioxide reduction",
            "CO2 electroreduction",
        ),
        "HER": (
            "HER",
            "hydrogen evolution reaction",
        ),
        "OER": (
            "OER",
            "oxygen evolution reaction",
        ),
        "ORR": (
            "ORR",
            "oxygen reduction reaction",
        ),
        "NRR": (
            "NRR",
            "nitrogen reduction reaction",
            "electrochemical ammonia synthesis",
        ),
    }

    PRODUCT_EXPANSIONS = {
        "CO": ("CO", "carbon monoxide"),
        "HCOOH/HCOO-": (
            "HCOOH",
            "HCOO-",
            "formic acid",
            "formate",
        ),
        "HCOO-": (
            "HCOO-",
            "formate",
            "formic acid",
        ),
        "CH3OH": ("CH3OH", "methanol"),
        "C2H4": ("C2H4", "ethylene"),
        "H2": ("H2", "hydrogen"),
        "O2": ("O2", "oxygen"),
        "NH3": ("NH3", "ammonia"),
    }

    def __init__(
        self,
        quality_evaluator: (
            EvidenceQualityEvaluator | None
        ) = None,
    ) -> None:
        self.quality_evaluator = (
            quality_evaluator
            or EvidenceQualityEvaluator()
        )

    def merge(
        self,
        local_result: dict[str, Any],
        online_result: dict[str, Any],
        question: str,
        task_analysis: dict[str, Any] | None = None,
        keywords: list[str] | None = None,
        final_count: int = 5,
        excluded_identities: set[str] | None = None,
    ) -> dict[str, Any]:
        """合并、去重、评价并重排本地和在线文献。"""

        if not isinstance(local_result, dict):
            raise TypeError("local_result 必须是字典。")

        if not isinstance(online_result, dict):
            raise TypeError("online_result 必须是字典。")

        if not question.strip():
            raise ValueError("用户问题不能为空。")

        if final_count <= 0:
            raise ValueError("final_count 必须大于 0。")

        task_analysis = task_analysis or {}
        keywords = keywords or []

        local_papers = self._read_papers(
            local_result.get("selected", []),
            origin="local",
        )

        online_papers = self._read_papers(
            online_result.get("candidates", []),
            origin="online",
        )

        combined = [
            *local_papers,
            *online_papers,
        ]

        excluded = set(excluded_identities or set())
        excluded_count = 0
        if excluded:
            retained = []
            for paper in combined:
                if self._identities(paper) & excluded:
                    excluded_count += 1
                else:
                    retained.append(paper)
            combined = retained

        deduplicated, duplicate_groups = (
            self._deduplicate(combined)
        )

        evaluated = (
            self.quality_evaluator.evaluate_many(
                papers=deduplicated,
                task_analysis=task_analysis,
            )
        )

        ranking_query = self._ranking_query(
            question=question,
            task_analysis=task_analysis,
            keywords=keywords,
        )

        ranked = [
            self._add_ranking_scores(
                paper=paper,
                ranking_query=ranking_query,
            )
            for paper in evaluated
        ]

        ranked.sort(
            key=lambda paper: (
                -paper["merged_ranking_scores"][
                    "combined"
                ],
                -paper["evidence_quality"][
                    "quality_score"
                ],
                -(paper.get("year") or 0),
                paper.get("title", ""),
            )
        )

        required_reaction = str(
            task_analysis.get("reaction_family", "") or ""
        ).strip()
        task_mismatch_rejected = [
            paper
            for paper in ranked
            if required_reaction
            and not paper["evidence_quality"].get(
                "reaction_direct", False
            )
        ]
        quality_rejected = [
            paper
            for paper in ranked
            if paper["evidence_quality"]["quality_level"] == "D"
        ]
        eligible = [
            paper
            for paper in ranked
            if paper["evidence_quality"]["quality_level"] != "D"
            and (
                not required_reaction
                or paper["evidence_quality"].get(
                    "reaction_direct", False
                )
            )
        ]
        rejected = [
            paper for paper in ranked if paper not in eligible
        ]

        selected = eligible[:final_count]

        for index, paper in enumerate(
            selected,
            start=1,
        ):
            paper["merged_rank"] = index
            paper["evidence_id"] = f"E{index}"
            paper["review_status"] = (
                "pending_review"
            )

        return {
            "status": "completed",
            "question": question,
            "ranking_query": ranking_query,
            "local_input_count": len(
                local_papers
            ),
            "online_input_count": len(
                online_papers
            ),
            "combined_input_count": len(
                combined
            ),
            "excluded_previous_rejections": excluded_count,
            "unique_count": len(
                deduplicated
            ),
            "duplicate_count": (
                len(combined)
                - len(deduplicated)
            ),
            "duplicate_group_count": len(
                duplicate_groups
            ),
            "eligible_count": len(
                eligible
            ),
            "task_reaction_required": bool(required_reaction),
            "target_product_required": False,
            "task_mismatch_rejected_count": len(task_mismatch_rejected),
            "task_mismatch_rejected": task_mismatch_rejected,
            "quality_rejected_count": len(quality_rejected),
            "quality_rejected": quality_rejected,
            "selected_count": len(
                selected
            ),
            "selected": selected,
            "rejected": rejected,
            "duplicate_groups": duplicate_groups,
            "ranking_method": (
                "0.55 * lexical_relevance + "
                "0.35 * evidence_quality + "
                "0.10 * recency"
            ),
            "warnings": [
                (
                    "标题去重只处理规范化后完全相同的"
                    "标题，不进行语义级模糊合并。"
                ),
                (
                    "预印本与正式论文版本仍需要在"
                    " B6 由人工确认。"
                ),
                (
                    "B1 分数评价元数据完整度和词法"
                    "相关性，不代表论文结论一定可靠。"
                ),
            ],
        }

    @staticmethod
    def _read_papers(
        values: Any,
        origin: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(values, list):
            return []

        papers: list[dict[str, Any]] = []

        for value in values:
            if not isinstance(value, dict):
                continue

            paper = dict(value)
            paper["_merge_origin"] = origin
            papers.append(paper)

        return papers

    def _deduplicate(
        self,
        papers: list[dict[str, Any]],
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """
        使用多个确定性标识合并重复记录。

        优先标识：
        1. DOI；
        2. OpenAlex ID；
        3. 规范化后完全相同的标题。

        不使用模糊标题相似度，避免错误合并不同论文。
        """

        groups: list[dict[str, Any]] = []

        for paper in papers:
            identities = self._identities(paper)

            matching_indexes = [
                index
                for index, group in enumerate(groups)
                if identities & group["identities"]
            ]

            if not matching_indexes:
                groups.append(
                    {
                        "identities": set(identities),
                        "records": [paper],
                    }
                )
                continue

            first_index = matching_indexes[0]
            target = groups[first_index]

            target["identities"].update(
                identities
            )
            target["records"].append(paper)

            # 如果一条记录同时连接两个已有分组，
            # 将这两个分组合并，保持去重的传递性。
            for index in reversed(
                matching_indexes[1:]
            ):
                target["identities"].update(
                    groups[index]["identities"]
                )
                target["records"].extend(
                    groups[index]["records"]
                )
                del groups[index]

        merged: list[dict[str, Any]] = []
        duplicate_groups: list[
            dict[str, Any]
        ] = []

        for group in groups:
            records = group["records"]
            canonical = self._merge_group(records)
            merged.append(canonical)

            if len(records) > 1:
                duplicate_groups.append(
                    {
                        "canonical_paper_id": (
                            canonical.get(
                                "paper_id",
                                "",
                            )
                        ),
                        "canonical_title": (
                            canonical.get(
                                "title",
                                "",
                            )
                        ),
                        "record_count": len(records),
                        "matched_identities": sorted(
                            group["identities"]
                        ),
                        "paper_ids": sorted(
                            {
                                str(
                                    record.get(
                                        "paper_id",
                                        "",
                                    )
                                )
                                for record in records
                                if record.get(
                                    "paper_id"
                                )
                            }
                        ),
                        "dois": sorted(
                            {
                                self._normalize_doi(
                                    record.get(
                                        "doi",
                                        "",
                                    )
                                )
                                for record in records
                                if self._normalize_doi(
                                    record.get(
                                        "doi",
                                        "",
                                    )
                                )
                            }
                        ),
                    }
                )

        return merged, duplicate_groups

    def _merge_group(
        self,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        在重复记录中选择主版本，并补齐缺失元数据。

        选择顺序：
        正式期刊版本 > 未知版本 > 预印本版本。
        同类版本中优先保留元数据更完整者。
        """

        ordered = sorted(
            records,
            key=self._record_preference,
            reverse=True,
        )

        canonical = dict(ordered[0])

        fillable_fields = (
            "paper_id",
            "title",
            "abstract",
            "year",
            "journal",
            "doi",
            "url",
            "source",
            "summary",
            "issns",
        )

        for record in ordered[1:]:
            for field in fillable_fields:
                if not canonical.get(field):
                    value = record.get(field)
                    if value:
                        canonical[field] = value

        canonical["assertions"] = (
            self._merge_assertions(records)
        )

        verified_records = [
            record
            for record in records
            if record.get("metadata_verified", False)
        ]
        canonical["metadata_verified"] = bool(verified_records)
        canonical["metadata_provider"] = "+".join(sorted({
            str(record.get("metadata_provider", "") or "").strip().lower()
            for record in verified_records
            if str(record.get("metadata_provider", "") or "").strip()
        }))
        canonical["claim_evidence_available"] = bool(
            canonical.get("abstract")
            and any(
                record.get("claim_evidence_available", False)
                for record in records
            )
        )
        cross_verified_records = [
            record
            for record in records
            if record.get("cross_verified", False)
            or record.get("kimi_cross_verified", False)
        ]
        canonical["cross_verified"] = bool(cross_verified_records)
        canonical["kimi_cross_verified"] = bool(cross_verified_records)
        verification = {
            "crossref_verified": any(
                record.get("cross_verification", {}).get(
                    "crossref_verified", False
                )
                or (
                    record.get("metadata_verified", False)
                    and "crossref" in str(
                        record.get("metadata_provider", "") or ""
                    ).lower()
                )
                for record in records
            ),
            "semantic_scholar_verified": any(
                record.get("cross_verification", {}).get(
                    "semantic_scholar_verified", False
                )
                or (
                    record.get("metadata_verified", False)
                    and "semantic" in str(
                        record.get("metadata_provider", "") or ""
                    ).lower()
                )
                for record in records
            ),
            "required_tools_called": any(
                record.get("cross_verification", {}).get(
                    "required_tools_called", False
                )
                for record in records
            ),
            "cross_verified": bool(cross_verified_records),
        }
        canonical["cross_verification"] = verification
        if cross_verified_records:
            verified = cross_verified_records[0]
            canonical["cross_verification"].update(
                verified.get("cross_verification", {})
            )
            for field in (
                "semantic_scholar_id",
                "citation_count",
                "open_access_pdf_url",
            ):
                if verified.get(field) not in (None, ""):
                    canonical[field] = verified[field]

        origins = sorted(
            {
                str(
                    record.get(
                        "_merge_origin",
                        "",
                    )
                )
                for record in records
                if record.get("_merge_origin")
            }
        )

        statuses = [
            self._publication_status(record)
            for record in records
        ]

        canonical.pop("_merge_origin", None)

        canonical["retrieval_origin"] = (
            "+".join(origins)
        )

        canonical["stored_in_repository"] = (
            "local" in origins
        )

        canonical["review_status"] = (
            "pending_review"
        )

        canonical["embedding_text"] = " ".join(
            str(canonical.get(field, "") or "")
            for field in (
                "title",
                "abstract",
                "summary",
            )
            if canonical.get(field)
        )

        canonical["version_info"] = {
            "record_count": len(records),
            "is_multi_record": len(records) > 1,
            "has_preprint_version": (
                "preprint" in statuses
            ),
            "has_formal_version": (
                "formal" in statuses
            ),
            "canonical_status": (
                self._publication_status(
                    canonical
                )
            ),
            "paper_ids": sorted(
                {
                    str(
                        record.get(
                            "paper_id",
                            "",
                        )
                    )
                    for record in records
                    if record.get("paper_id")
                }
            ),
            "dois": sorted(
                {
                    self._normalize_doi(
                        record.get("doi", "")
                    )
                    for record in records
                    if self._normalize_doi(
                        record.get("doi", "")
                    )
                }
            ),
        }

        return canonical

    @staticmethod
    def _merge_assertions(
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        assertions: list[dict[str, Any]] = []
        seen: set[str] = set()

        for record in records:
            values = record.get(
                "assertions",
                [],
            )

            if not isinstance(values, list):
                continue

            for value in values:
                if not isinstance(value, dict):
                    continue

                identity = json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                )

                if identity in seen:
                    continue

                seen.add(identity)
                assertions.append(dict(value))

        return assertions

    def _record_preference(
        self,
        paper: dict[str, Any],
    ) -> tuple[int, int, int, int]:
        status_scores = {
            "formal": 2,
            "unknown": 1,
            "preprint": 0,
        }

        status_score = status_scores[
            self._publication_status(paper)
        ]

        metadata_score = sum(
            (
                2 if paper.get("title") else 0,
                2 if paper.get("abstract") else 0,
                2 if paper.get("doi") else 0,
                1 if paper.get("journal") else 0,
                1 if paper.get("year") else 0,
                1 if paper.get("url") else 0,
                1 if paper.get("paper_id") else 0,
            )
        )

        abstract_length = len(
            str(paper.get("abstract", "") or "")
        )

        local_score = int(
            paper.get("_merge_origin") == "local"
        )

        return (
            status_score,
            metadata_score,
            abstract_length,
            local_score,
        )

    def _publication_status(
        self,
        paper: dict[str, Any],
    ) -> str:
        searchable = " ".join(
            str(
                paper.get(field, "") or ""
            ).lower()
            for field in (
                "journal",
                "source",
                "url",
            )
        )

        if any(
            marker in searchable
            for marker in self.PREPRINT_MARKERS
        ):
            return "preprint"

        if str(
            paper.get("journal", "") or ""
        ).strip():
            return "formal"

        return "unknown"

    def _identities(
        self,
        paper: dict[str, Any],
    ) -> set[str]:
        identities: set[str] = set()

        doi = self._normalize_doi(
            paper.get("doi", "")
        )
        if doi:
            identities.add(f"doi:{doi}")

        openalex_id = self._normalize_openalex_id(
            paper.get("paper_id", "")
        )
        if openalex_id:
            identities.add(
                f"openalex:{openalex_id}"
            )

        title = self._normalize_title(
            paper.get("title", "")
        )
        if title:
            identities.add(f"title:{title}")

        if not identities:
            identities.add(
                f"unknown:{id(paper)}"
            )

        return identities

    @staticmethod
    def _normalize_doi(value: Any) -> str:
        doi = str(value or "").strip().lower()

        prefixes = (
            "https://doi.org/",
            "http://doi.org/",
            "doi:",
        )

        for prefix in prefixes:
            if doi.startswith(prefix):
                doi = doi[len(prefix):]

        return doi.strip().rstrip(".")

    @staticmethod
    def _normalize_openalex_id(
        value: Any,
    ) -> str:
        paper_id = str(
            value or ""
        ).strip().lower()

        if paper_id.startswith(
            "https://openalex.org/"
        ):
            return paper_id.rsplit("/", 1)[-1]

        if paper_id.startswith("openalex:"):
            return paper_id.split(":", 1)[1]

        return ""

    @staticmethod
    def _normalize_title(value: Any) -> str:
        title = html.unescape(
            str(value or "")
        )

        title = re.sub(
            r"<[^>]+>",
            "",
            title,
        )

        title = title.lower()

        title = re.sub(
            r"[^a-z0-9\u4e00-\u9fff]+",
            " ",
            title,
        )

        return " ".join(title.split())

    def _ranking_query(
        self,
        question: str,
        task_analysis: dict[str, Any],
        keywords: list[str],
    ) -> str:
        parts = [question, *keywords]

        reaction = str(
            task_analysis.get(
                "reaction_family",
                "",
            )
            or ""
        ).upper()

        product = str(
            task_analysis.get(
                "target_product",
                "",
            )
            or ""
        ).upper()

        parts.extend(
            self.REACTION_EXPANSIONS.get(
                reaction,
                (),
            )
        )

        parts.extend(
            self.PRODUCT_EXPANSIONS.get(
                product,
                (),
            )
        )

        combined = " ".join(parts).lower()

        if (
            "高熵" in combined
            or "high entropy" in combined
        ):
            parts.extend(
                (
                    "high entropy alloy",
                    "high entropy catalyst",
                )
            )

        unique_parts: list[str] = []

        for part in parts:
            value = str(part).strip()
            if (
                value
                and value.lower()
                not in {
                    item.lower()
                    for item in unique_parts
                }
            ):
                unique_parts.append(value)

        return " ".join(unique_parts)

    def _add_ranking_scores(
        self,
        paper: dict[str, Any],
        ranking_query: str,
    ) -> dict[str, Any]:
        item = dict(paper)

        query_terms = self._terms(
            ranking_query
        )

        title_terms = self._terms(
            str(item.get("title", "") or "")
        )

        document_terms = self._terms(
            " ".join(
                (
                    str(
                        item.get("title", "")
                        or ""
                    ),
                    str(
                        item.get("abstract", "")
                        or ""
                    ),
                    str(
                        item.get("summary", "")
                        or ""
                    ),
                    str(item.get("composition_raw", "") or ""),
                    " ".join(str(value) for value in item.get("reaction_labels", [])),
                    " ".join(str(value) for value in item.get("keywords", [])),
                    str(item.get("evidence_snippet", "") or ""),
                )
            )
        )

        if query_terms:
            document_coverage = (
                len(
                    query_terms
                    & document_terms
                )
                / len(query_terms)
            )

            title_coverage = (
                len(
                    query_terms
                    & title_terms
                )
                / len(query_terms)
            )
        else:
            document_coverage = 0.0
            title_coverage = 0.0

        lexical_relevance = (
            0.70 * document_coverage
            + 0.30 * title_coverage
        )

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

        recency = self._recency_score(
            item.get("year")
        )

        local_source = 1.0 if item.get("_merge_origin") == "local" else 0.0

        combined = (
            0.50 * lexical_relevance
            + 0.35 * quality_normalized
            + 0.10 * recency
            + 0.05 * local_source
        )

        item["merged_ranking_scores"] = {
            "document_coverage": round(
                document_coverage,
                6,
            ),
            "title_coverage": round(
                title_coverage,
                6,
            ),
            "lexical_relevance": round(
                lexical_relevance,
                6,
            ),
            "quality_normalized": round(
                quality_normalized,
                6,
            ),
            "recency": round(
                recency,
                6,
            ),
            "local_source": local_source,
            "combined": round(
                combined,
                6,
            ),
        }

        return item

    @staticmethod
    def _recency_score(value: Any) -> float:
        try:
            year = int(value)
        except (TypeError, ValueError):
            return 0.0

        current_year = datetime.now().year
        age = max(0, current_year - year)

        if age >= 10:
            return 0.0

        return 1.0 - age / 10.0

    @staticmethod
    def _terms(value: str) -> set[str]:
        return set(
            re.findall(
                r"[a-z0-9*+-]{2,}|"
                r"[\u4e00-\u9fff]{2,}",
                value.lower(),
            )
        )
