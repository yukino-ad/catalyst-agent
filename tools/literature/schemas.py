from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

EvidenceLevel = Literal["explicit", "inferred", "missing"]
Confidence = Literal["high", "medium", "low"]


@dataclass
class Evidence:
    quote: str
    source: Literal["title", "abstract"]
    sentence_index: int | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | str) -> "Evidence":
        if isinstance(value, str):
            return cls(
                quote=value.strip(),
                source="abstract",
                sentence_index=None,
            )

        if not isinstance(value, dict):
            return cls(
                quote="",
                source="abstract",
                sentence_index=None,
            )

        source = value.get("source", "abstract")
        if source not in {"title", "abstract"}:
            source = "abstract"

        sentence_index = value.get("sentence_index")
        if not isinstance(sentence_index, int):
            sentence_index = None

        return cls(
            quote=str(value.get("quote", "")).strip(),
            source=source,
            sentence_index=sentence_index,
        )


@dataclass
class Assertion:
    kind: Literal[
        "reaction", "product", "element_set", "intermediate", "pathway",
        "material_family", "performance_metric", "catalytic_claim",
        "stability_claim", "synthesis_method",
    ]
    value: str | list[str] | dict[str, Any]
    evidence_level: EvidenceLevel = "missing"
    confidence: Confidence = "low"
    evidence: list[Evidence] = field(default_factory=list)
    inferred: bool = False
    assertion_id: str = ""
    validation_status: str = "pending"
    review_status: str = "pending_review"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Assertion":
        raw_evidence = value.get("evidence", [])
        if isinstance(raw_evidence, (str, dict)):
            raw_evidence = [raw_evidence]
        elif not isinstance(raw_evidence, list):
            raw_evidence = []

        evidence = [
            Evidence.from_dict(item)
            for item in raw_evidence
            if isinstance(item, (str, dict))
        ]
        evidence = [item for item in evidence if item.quote]

        evidence_level = value.get("evidence_level", "missing")
        if evidence_level not in {"explicit", "inferred", "missing"}:
            evidence_level = "missing"

        confidence = value.get("confidence", "low")
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"

        return cls(
            kind=str(value.get("kind", "")).strip(),
            value=value.get("value", ""),
            evidence_level=evidence_level,
            confidence=confidence,
            evidence=evidence,
            inferred=(value.get("inferred", False) is True),
            assertion_id=str(value.get("assertion_id", "") or ""),
            validation_status=str(value.get("validation_status", "pending") or "pending"),
            review_status=str(value.get("review_status", "pending_review") or "pending_review"),
        )


@dataclass
class PaperRecord:
    paper_id: str
    title: str
    abstract: str = ""
    year: int | None = None
    journal: str = ""
    doi: str = ""
    url: str = ""
    source: str = "OpenAlex"
    publication_type: str = ""
    is_retracted: bool = False
    is_corrected: bool = False
    journal_impact_factor: float | None = None
    journal_metric_year: int | None = None
    journal_metric_source: str = ""
    openalex_source_id: str = ""
    issn_l: str = ""
    issns: list[str] = field(default_factory=list)
    metadata_verified: bool = False
    metadata_provider: str = ""
    claim_evidence_available: bool = False
    cross_verified: bool = False
    kimi_cross_verified: bool = False
    semantic_scholar_id: str = ""
    citation_count: int = 0
    open_access_pdf_url: str = ""
    cross_verification: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    source_file: str = ""
    source_sheet: str = ""
    source_row: int | None = None
    composition_raw: str = ""
    reaction_labels: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    evidence_snippet: str = ""
    context_misread_flag: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)
    assertions: list[Assertion] = field(default_factory=list)

    @property
    def embedding_text(self) -> str:
        structured = " ".join(
            [
                self.composition_raw,
                " ".join(self.reaction_labels),
                " ".join(self.keywords),
                self.evidence_snippet,
            ]
        )
        return " ".join(
            part for part in (self.title, self.abstract, self.summary, structured)
            if part
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["embedding_text"] = self.embedding_text
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PaperRecord":
        return cls(
            paper_id=str(value["paper_id"]),
            title=str(value.get("title", "")).strip(),
            abstract=str(value.get("abstract", "")).strip(),
            year=value.get("year"),
            journal=str(value.get("journal", "") or ""),
            doi=str(value.get("doi", "") or ""),
            url=str(value.get("url", "") or ""),
            source=str(value.get("source", "OpenAlex")),
            publication_type=str(value.get("publication_type", "") or ""),
            is_retracted=(value.get("is_retracted", False) is True),
            is_corrected=(value.get("is_corrected", False) is True),
            journal_impact_factor=value.get("journal_impact_factor"),
            journal_metric_year=value.get("journal_metric_year"),
            journal_metric_source=str(value.get("journal_metric_source", "") or ""),
            openalex_source_id=str(value.get("openalex_source_id", "") or ""),
            issn_l=str(value.get("issn_l", "") or ""),
            issns=[str(item) for item in value.get("issns", []) if str(item)],
            metadata_verified=(value.get("metadata_verified", False) is True),
            metadata_provider=str(value.get("metadata_provider", "") or ""),
            claim_evidence_available=(
                value.get(
                    "claim_evidence_available", bool(value.get("abstract"))
                ) is True
            ),
            cross_verified=(value.get("cross_verified", False) is True),
            kimi_cross_verified=(
                value.get(
                    "kimi_cross_verified", value.get("cross_verified", False)
                ) is True
            ),
            semantic_scholar_id=str(
                value.get("semantic_scholar_id", "") or ""
            ),
            citation_count=int(value.get("citation_count", 0) or 0),
            open_access_pdf_url=str(
                value.get("open_access_pdf_url", "") or ""
            ),
            cross_verification=dict(
                value.get("cross_verification", {})
                if isinstance(value.get("cross_verification", {}), dict)
                else {}
            ),
            summary=str(value.get("summary", "") or ""),
            source_file=str(value.get("source_file", "") or ""),
            source_sheet=str(value.get("source_sheet", "") or ""),
            source_row=value.get("source_row"),
            composition_raw=str(value.get("composition_raw", "") or ""),
            reaction_labels=[
                str(item) for item in value.get("reaction_labels", [])
                if str(item).strip()
            ],
            keywords=[
                str(item) for item in value.get("keywords", [])
                if str(item).strip()
            ],
            evidence_snippet=str(value.get("evidence_snippet", "") or ""),
            context_misread_flag=(value.get("context_misread_flag", False) is True),
            provenance=dict(value.get("provenance", {}) or {}),
            assertions=[Assertion.from_dict(item) for item in value.get("assertions", [])],
        )
