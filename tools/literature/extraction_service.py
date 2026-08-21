from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.literature.evidence_quality import EvidenceQualityEvaluator
from tools.literature.extractor import LiteratureExtractor
from tools.literature.journal_metrics import JournalMetricRegistry
from tools.literature.schemas import PaperRecord
from tools.literature.semantic_scholar_client import (
    SemanticScholarClient,
    SemanticScholarRateLimitError,
)


class LiteratureAssertionExtractionService:
    """Extract, validate, cache, and finally score merged literature."""

    SCHEMA_VERSION = "b1-extraction-v1"
    MAX_LLM_PAPERS = 5

    def __init__(
        self,
        extractor: LiteratureExtractor | None = None,
        evaluator: EvidenceQualityEvaluator | None = None,
        metrics: JournalMetricRegistry | None = None,
        semantic_scholar: SemanticScholarClient | None = None,
        cache_dir: str | Path = "database/literature/extractions",
    ) -> None:
        self.extractor = extractor or LiteratureExtractor()
        self.evaluator = evaluator or EvidenceQualityEvaluator()
        self.metrics = metrics or JournalMetricRegistry()
        self.semantic_scholar = semantic_scholar or SemanticScholarClient()
        path = Path(cache_dir)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        path.mkdir(parents=True, exist_ok=True)
        self.cache_dir = path

    def process(
        self,
        papers: list[dict[str, Any]],
        task_analysis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        input_count = len(papers)
        papers, enrichment = self._enrich_missing_abstracts(papers)
        papers, prefilter_rejected = self._prefilter_candidates(
            papers, task_analysis
        )
        print(
            "[B1] Strict prefilter: "
            f"{len(papers)}/{input_count} eligible; "
            f"{len(prefilter_rejected)} excluded before deep extraction.",
            flush=True,
        )
        results = []
        cache_hits = 0
        failures = []
        llm_candidate_ids = self._llm_candidate_ids(papers, task_analysis)
        for index, paper in enumerate(papers, 1):
            title = str(paper.get("title", "") or "Untitled paper")
            print(
                f"[B1] Extracting paper {index}/{len(papers)}: {title[:90]}",
                flush=True,
            )
            try:
                enriched = self.metrics.enrich(paper)
                enriched["preliminary_evidence_quality"] = self.evaluator.evaluate(
                    enriched, task_analysis
                )
                extracted, cache_hit, mode = self._extract(
                    enriched,
                    allow_llm=self._paper_identity(enriched) in llm_candidate_ids,
                )
                cache_hits += int(cache_hit)
                # Ranking IDs belong to the current run, never to cached data.
                extracted["evidence_id"] = str(
                    paper.get("evidence_id") or f"E{index}"
                )
                for assertion_index, assertion in enumerate(
                    extracted.get("assertions", []), 1
                ):
                    assertion["assertion_id"] = (
                        f"{extracted['evidence_id']}::A{assertion_index}"
                    )
                extracted["extraction_status"] = "completed"
                extracted["extraction_mode"] = mode
                extracted["evidence_quality"] = self.evaluator.evaluate(
                    extracted, task_analysis
                )
                extracted["evidence_quality"]["evaluation_phase"] = "final"
                results.append(extracted)
                print(
                    f"[B1] Paper {index}/{len(papers)} completed: {mode}",
                    flush=True,
                )
            except Exception as error:
                fallback = self.metrics.enrich(paper)
                fallback["extraction_status"] = "failed"
                fallback["extraction_error"] = str(error)
                fallback["evidence_quality"] = self.evaluator.evaluate(
                    fallback, task_analysis
                )
                fallback["evidence_quality"]["evaluation_phase"] = "preliminary"
                results.append(fallback)
                failures.append({
                    "paper_id": paper.get("paper_id", ""),
                    "error_type": type(error).__name__,
                    "message": str(error),
                })
                print(
                    f"[B1] Paper {index}/{len(papers)} failed: {error}",
                    flush=True,
                )
        results.sort(key=lambda paper: (
            not bool(paper.get("evidence_quality", {}).get("hea_composition_eligible")),
            -float(paper.get("evidence_quality", {}).get("core_scientific_score", 0)),
            -float(paper.get("evidence_quality", {}).get("quality_score", 0)),
            -(paper.get("year") or 0),
        ))
        for index, paper in enumerate(results, 1):
            paper["b1_final_rank"] = index
        llm_errors = list(dict.fromkeys(
            str(paper.get("llm_extraction_error", "")).strip()
            for paper in results
            if str(paper.get("llm_extraction_error", "")).strip()
        ))
        llm_fallback_count = sum(
            paper.get("extraction_mode")
            == "deterministic_fallback_after_llm_error"
            for paper in results
        )
        journal_metric_coverage_count = sum(
            paper.get("evidence_quality", {})
            .get("journal_impact", {})
            .get("status") == "verified"
            for paper in results
        )
        return {
            "schema_version": self.SCHEMA_VERSION,
            "status": "literature_assertion_extraction_completed" if not failures else "literature_assertion_extraction_completed_with_errors",
            "paper_count": len(results),
            "input_paper_count": input_count,
            "prefilter_passed_count": len(papers),
            "prefilter_rejected_count": len(prefilter_rejected),
            "prefilter_rejected": prefilter_rejected,
            "semantic_scholar_enrichment": enrichment,
            "cache_hit_count": cache_hits,
            "failure_count": len(failures),
            "llm_candidate_count": len(llm_candidate_ids),
            "llm_candidate_limit": self.MAX_LLM_PAPERS,
            "llm_fallback_count": llm_fallback_count,
            "llm_errors": llm_errors,
            "journal_metric_coverage_count": journal_metric_coverage_count,
            "journal_metric_missing_count": (
                len(results) - journal_metric_coverage_count
            ),
            "papers": results,
            "failures": failures,
        }

    def _enrich_missing_abstracts(
        self,
        papers: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        enriched = []
        attempted = 0
        matched = 0
        errors = []
        rate_limited = False
        for original in papers:
            paper = dict(original)
            if not paper.get("abstract") and paper.get("doi") and not rate_limited:
                attempted += 1
                try:
                    match = self.semantic_scholar.find_by_doi(paper["doi"])
                    if match:
                        matched += 1
                        if match.get("abstract"):
                            paper["abstract"] = match["abstract"]
                            paper["claim_evidence_available"] = True
                        paper["semantic_scholar_id"] = match.get(
                            "semantic_scholar_id", ""
                        )
                        paper["citation_count"] = match.get("citation_count", 0)
                        paper["open_access_pdf_url"] = match.get(
                            "open_access_pdf_url", ""
                        )
                        verification = dict(paper.get("cross_verification", {}))
                        verification["semantic_scholar_verified"] = True
                        verification["semantic_scholar_match_method"] = "doi_exact"
                        paper["cross_verification"] = verification
                except SemanticScholarRateLimitError as error:
                    rate_limited = True
                    errors.append(str(error))
                except (OSError, ValueError, TypeError) as error:
                    errors.append(f"{type(error).__name__}: {error}")
            enriched.append(paper)
        return enriched, {
            "attempted_count": attempted,
            "matched_count": matched,
            "rate_limited": rate_limited,
            "errors": errors,
        }

    def _prefilter_candidates(
        self,
        papers: list[dict[str, Any]],
        task_analysis: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        eligible = []
        rejected = []
        required_reaction = str(
            (task_analysis or {}).get("reaction_family", "") or ""
        ).strip()
        for paper in papers:
            quality = self.evaluator.evaluate(paper, task_analysis)
            reasons = []
            if required_reaction and not quality.get("reaction_direct", False):
                reasons.append("target_reaction_not_explicit")
            if not quality.get("hea_direct", False):
                reasons.append("high_entropy_identity_not_explicit")
            if quality.get("composition_element_count", 0) != 5:
                reasons.append("explicit_five_metal_composition_not_found")
            if reasons:
                rejected.append({
                    "paper_id": paper.get("paper_id", ""),
                    "title": paper.get("title", ""),
                    "reasons": reasons,
                    "preliminary_evidence_quality": quality,
                })
            else:
                eligible.append(paper)
        return eligible, rejected

    def _extract(
        self,
        paper: dict[str, Any],
        allow_llm: bool = True,
    ) -> tuple[dict[str, Any], bool, str]:
        cache_path = self.cache_dir / f"{self._cache_key(paper, allow_llm)}.json"
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = deepcopy(payload["paper"])
            for field in (
                "metadata_verified",
                "metadata_provider",
                "claim_evidence_available",
                "cross_verified",
                "kimi_cross_verified",
                "semantic_scholar_id",
                "citation_count",
                "open_access_pdf_url",
                "cross_verification",
            ):
                if field in paper:
                    cached[field] = deepcopy(paper[field])
            return cached, True, str(payload.get("mode", "cache"))
        record = PaperRecord.from_dict(paper)
        mode = "deterministic_fallback"
        if allow_llm and self.extractor.llm.available and record.abstract:
            try:
                record = self.extractor.extract(record)
                mode = "llm_validated"
            except Exception as error:
                record.assertions = self.extractor.deterministic_extract(record)
                record.summary = record.abstract
                mode = "deterministic_fallback_after_llm_error"
                paper["llm_extraction_error"] = str(error)
        else:
            record.assertions = self.extractor.deterministic_extract(record)
            record.summary = record.abstract
        result = {**paper, **record.to_dict()}
        for index, assertion in enumerate(result.get("assertions", []), 1):
            assertion["assertion_id"] = f"{result.get('evidence_id', 'E')}::A{index}"
            assertion["validation_status"] = "passed"
            assertion["review_status"] = "pending_review"
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "prompt_version": self.extractor.PROMPT_VERSION,
            "model": getattr(self.extractor.llm.settings, "model", ""),
            "mode": mode,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "paper": result,
        }
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return result, False, mode

    def _llm_candidate_ids(
        self,
        papers: list[dict[str, Any]],
        task_analysis: dict[str, Any] | None,
    ) -> set[str]:
        ranked = []
        for paper in papers:
            quality = self.evaluator.evaluate(paper, task_analysis)
            ranked.append((
                not bool(quality.get("hea_composition_eligible")),
                -float(quality.get("core_scientific_score", 0)),
                -float(quality.get("quality_score", 0)),
                self._paper_identity(paper),
            ))
        ranked.sort()
        return {
            identity
            for _, _, _, identity in ranked[:self.MAX_LLM_PAPERS]
        }

    @staticmethod
    def _paper_identity(paper: dict[str, Any]) -> str:
        return str(
            paper.get("paper_id")
            or paper.get("doi")
            or paper.get("title")
            or id(paper)
        )

    def _cache_key(
        self,
        paper: dict[str, Any],
        allow_llm: bool = True,
    ) -> str:
        text = json.dumps({
            "paper_id": paper.get("paper_id"),
            "title": paper.get("title"),
            "abstract": paper.get("abstract"),
            "metadata_verified": paper.get("metadata_verified", False),
            "metadata_provider": paper.get("metadata_provider", ""),
            "cross_verified": paper.get("cross_verified", False),
            "kimi_cross_verified": paper.get("kimi_cross_verified", False),
            "prompt_version": self.extractor.PROMPT_VERSION,
            "model": getattr(self.extractor.llm.settings, "model", ""),
            "extraction_tier": "llm" if allow_llm else "deterministic",
        }, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["LiteratureAssertionExtractionService"]
