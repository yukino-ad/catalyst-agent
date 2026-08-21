from __future__ import annotations

import re
from datetime import datetime
from typing import Any


class EvidenceQualityEvaluator:
    """Score paper metadata, task relevance, and quotable claims."""

    SCHEMA_VERSION = "b1.1"
    MAX_QUALITY_SCORE = 100.0
    WEIGHTS = {
        "metadata_quality": 20.0,
        "task_relevance": 30.0,
        "claim_evidence_quality": 30.0,
        "journal_impact": 20.0,
    }
    COMMON_HEA_TRANSITION_METALS = {"Cu", "Fe", "Ni", "Co", "Cr", "Mn"}
    METAL_SYMBOLS = (
        "Al", "Co", "Cr", "Cu", "Fe", "Ga", "Ge", "Mn", "Mo", "Ni",
        "Ti", "Zn", "Ag", "Pd", "Pt", "Au", "V", "Nb", "Ta", "W",
        "Ru", "Rh", "Ir", "Re", "Zr", "Hf", "Sc", "Y", "Mg", "Sn",
        "In", "Bi", "Sb", "Cd",
    )
    HEA_PATTERNS = (
        r"\bhigh[- ]entropy alloy(?:s)?\b",
        r"\bhigh[- ]entropy catalyst(?:s)?\b",
        r"\bhigh[- ]entropy material(?:s)?\b",
        r"\bhea(?:s)?\b",
        r"高熵合金",
        r"高熵催化剂",
    )
    PERFORMANCE_TERMS = (
        "faradaic efficiency", "current density", "overpotential",
        "selectivity", "turnover frequency", "mass activity",
        "specific activity", "conversion", "yield", "stability",
        "法拉第效率", "电流密度", "过电位", "选择性", "活性", "稳定性",
    )
    CONCLUSION_TERMS = (
        "demonstrate", "exhibit", "show", "achieve", "outperform",
        "enhance", "improve", "promote", "suppress", "indicate",
        "证明", "表现出", "实现", "优于", "提高", "促进", "抑制", "表明",
    )

    def evaluate(
        self,
        paper: dict[str, Any],
        task_analysis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_analysis = task_analysis or {}
        title = str(paper.get("title", "") or "").strip()
        abstract = str(paper.get("abstract", "") or "").strip()
        evidence_snippet = str(
            paper.get("evidence_snippet", "") or ""
        ).strip()
        doi = str(paper.get("doi", "") or "").strip()
        paper_id = str(paper.get("paper_id", "") or "").strip()
        journal = str(paper.get("journal", "") or "").strip()
        source = str(paper.get("source", "") or "").strip()
        publication_type = str(
            paper.get("publication_type", paper.get("work_type", "")) or ""
        ).strip().lower()
        year = self._safe_year(paper.get("year"))
        searchable = self._normalize_text(
            " ".join(
                [
                    title,
                    abstract,
                    str(paper.get("composition_raw", "") or ""),
                    " ".join(str(item) for item in paper.get("reaction_labels", [])),
                    " ".join(str(item) for item in paper.get("keywords", [])),
                    str(paper.get("evidence_snippet", "") or ""),
                ]
            )
        )

        reaction_family = str(
            task_analysis.get("reaction_family", "") or ""
        ).strip()
        target_product = str(
            task_analysis.get("target_product", "") or ""
        ).strip()
        material_family = str(
            task_analysis.get("material_family", "") or ""
        ).strip().lower()

        reaction_direct = self._reaction_is_direct(searchable, reaction_family)
        product_direct = self._product_is_direct(searchable, target_product)
        evidence_text = " ".join(
            part for part in (abstract, evidence_snippet) if part
        )
        hea_direct, hea_quotes = self._hea_evidence(title, evidence_text)
        composition = self._composition_evidence(paper, title, evidence_text)
        composition_elements = composition["elements"]
        composition_count = len(composition_elements)
        four_or_five_metals = composition_count in {4, 5}
        hea_composition_eligible = hea_direct and four_or_five_metals
        common_metals = sorted(
            set(composition_elements) & self.COMMON_HEA_TRANSITION_METALS
        )

        metadata = self._metadata_quality(
            title=title,
            abstract=abstract,
            doi=doi,
            paper_id=paper_id,
            journal=journal,
            source=source,
            year=year,
            publication_type=publication_type,
        )
        relevance = self._task_relevance(
            reaction_direct=reaction_direct,
            product_direct=product_direct,
            hea_direct=hea_direct,
            four_or_five_metals=four_or_five_metals,
            common_metal_count=len(common_metals),
            material_family=material_family,
        )
        claims = self._claim_evidence_quality(
            title=title,
            abstract=abstract,
            composition=composition,
            hea_quotes=hea_quotes,
        )
        journal_metric = self._journal_impact_score(paper)

        total_score = round(
            metadata["score"]
            + relevance["score"]
            + claims["score"]
            + journal_metric["score"],
            3,
        )
        is_retracted = paper.get("is_retracted", False) is True
        is_corrected = paper.get("is_corrected", False) is True
        quality_level = self._quality_level(
            total_score=total_score,
            metadata_score=metadata["score"],
            relevance_score=relevance["score"],
            claim_score=claims["score"],
            hea_composition_eligible=hea_composition_eligible,
            is_retracted=is_retracted,
        )

        issues = [*metadata["issues"], *relevance["issues"], *claims["issues"]]
        if journal_metric["status"] != "verified":
            issues.append(
                "Journal impact factor is unavailable or lacks a source/year; "
                "no journal-impact points were assigned."
            )
        if is_retracted:
            issues.append("Paper is marked as retracted and cannot be used as evidence.")
        if is_corrected:
            issues.append("Paper has a correction; the corrected version requires review.")

        return {
            "schema_version": self.SCHEMA_VERSION,
            "quality_level": quality_level,
            "quality_score": total_score,
            "quality_score_max": self.MAX_QUALITY_SCORE,
            "core_scientific_score": round(
                metadata["score"] + relevance["score"] + claims["score"], 3
            ),
            "core_scientific_score_max": 80.0,
            "evaluation_phase": "preliminary",
            "score_weights": dict(self.WEIGHTS),
            "metadata_quality": metadata,
            "task_relevance": relevance,
            "claim_evidence_quality": claims,
            "journal_impact": journal_metric,
            # Compatibility fields used by existing B2/B3/B5 code.
            "metadata_score": metadata["score"],
            "relevance_score": relevance["score"],
            "has_title": bool(title),
            "has_abstract": bool(abstract),
            "has_doi": bool(doi),
            "has_identifier": bool(doi or paper_id),
            "has_source": bool(journal or source),
            "has_year": year is not None,
            "reaction_direct": reaction_direct,
            "product_direct": product_direct,
            "hea_direct": hea_direct,
            "composition_elements": composition_elements,
            "composition_element_count": composition_count,
            "four_or_five_metals": four_or_five_metals,
            "hea_composition_eligible": hea_composition_eligible,
            "common_hea_transition_metals": common_metals,
            "is_retracted": is_retracted,
            "is_corrected": is_corrected,
            "metadata_verified": paper.get("metadata_verified", False) is True,
            "metadata_provider": str(paper.get("metadata_provider", "") or ""),
            "claim_evidence_available": bool(abstract),
            "evidence_scope": "title_abstract" if abstract else "title_only",
            "issues": list(dict.fromkeys(issues)),
            "requires_human_review": True,
            "scientific_boundary": (
                "Journal impact is a source-level aid and does not validate a "
                "paper's composition, performance, or conclusions."
            ),
        }

    def evaluate_many(
        self,
        papers: list[dict[str, Any]],
        task_analysis: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        evaluated: list[dict[str, Any]] = []
        for paper in papers:
            item = dict(paper)
            item["evidence_quality"] = self.evaluate(item, task_analysis)
            evaluated.append(item)
        return evaluated

    @staticmethod
    def _metadata_quality(**values: Any) -> dict[str, Any]:
        checks = {
            "title": (3.0, bool(values["title"])),
            "abstract": (4.0, bool(values["abstract"])),
            "doi": (4.0, bool(values["doi"])),
            "identifier": (2.0, bool(values["doi"] or values["paper_id"])),
            "journal_or_source": (3.0, bool(values["journal"] or values["source"])),
            "year": (2.0, values["year"] is not None),
            "publication_type": (2.0, bool(values["publication_type"])),
        }
        score = sum(points for points, passed in checks.values() if passed)
        issues = [f"Missing metadata field: {name}" for name, (_, passed) in checks.items() if not passed]
        return {
            "score": score,
            "max_score": 20.0,
            "checks": {name: passed for name, (_, passed) in checks.items()},
            "issues": issues,
        }

    @staticmethod
    def _task_relevance(
        reaction_direct: bool,
        product_direct: bool,
        hea_direct: bool,
        four_or_five_metals: bool,
        common_metal_count: int,
        material_family: str,
    ) -> dict[str, Any]:
        material_requested = material_family in {"high_entropy_alloy", "hea"}
        components = {
            "reaction": 15.0 if reaction_direct else 0.0,
            "target_product": 0.0,
            "high_entropy_material": 9.0 if hea_direct else 0.0,
            "four_or_five_metal_composition": 4.0 if four_or_five_metals else 0.0,
            "common_hea_transition_metals": min(2.0, common_metal_count * 0.4),
        }
        issues: list[str] = []
        if not reaction_direct:
            issues.append("Title/abstract does not directly identify the target reaction.")
        if material_requested and not hea_direct:
            issues.append("The paper does not explicitly identify a high-entropy material.")
        if not four_or_five_metals:
            issues.append("No explicit four- or five-metal composition was found.")
        return {
            "score": round(sum(components.values()), 3),
            "max_score": 30.0,
            "components": components,
            "issues": issues,
        }

    def _claim_evidence_quality(
        self,
        title: str,
        abstract: str,
        composition: dict[str, Any],
        hea_quotes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        performance_quotes = self._matching_sentences(
            title, abstract, self.PERFORMANCE_TERMS, require_number=True
        )
        conclusion_quotes = self._matching_sentences(
            title, abstract, self.CONCLUSION_TERMS, require_number=False
        )
        composition_score = 14.0 if len(composition["elements"]) in {4, 5} and composition["quotes"] else 0.0
        components = {
            "explicit_composition_quote": composition_score,
            "explicit_high_entropy_quote": 4.0 if hea_quotes else 0.0,
            "performance_quote": 6.0 if performance_quotes else 0.0,
            "conclusion_quote": 6.0 if conclusion_quotes else 0.0,
        }
        issues = []
        if not composition_score:
            issues.append("No quotable explicit four- or five-metal composition claim.")
        if not hea_quotes:
            issues.append("No quotable high-entropy designation.")
        if not performance_quotes:
            issues.append("No quantitative performance claim was found in title/abstract.")
        if not conclusion_quotes:
            issues.append("No quotable conclusion claim was found in title/abstract.")
        return {
            "score": sum(components.values()),
            "max_score": 30.0,
            "components": components,
            "composition_claims": composition["quotes"],
            "high_entropy_claims": hea_quotes,
            "performance_claims": performance_quotes,
            "conclusion_claims": conclusion_quotes,
            "issues": issues,
        }

    @staticmethod
    def _journal_impact_score(paper: dict[str, Any]) -> dict[str, Any]:
        raw = paper.get("journal_impact_factor")
        source = str(paper.get("journal_metric_source", "") or "").strip()
        metric_year = EvidenceQualityEvaluator._safe_year(
            paper.get("journal_metric_year")
        )
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
        verified = value > 0 and bool(source) and metric_year is not None
        if not verified:
            score = 0.0
            status = "unavailable"
        elif value >= 20:
            score = 20.0
            status = "verified"
        elif value >= 15:
            score = 18.0
            status = "verified"
        elif value >= 10:
            score = 16.0
            status = "verified"
        elif value >= 7:
            score = 14.0
            status = "verified"
        elif value >= 5:
            score = 12.0
            status = "verified"
        elif value >= 3:
            score = 9.0
            status = "verified"
        elif value >= 1:
            score = 6.0
            status = "verified"
        else:
            score = 3.0
            status = "verified"
        return {
            "score": score,
            "max_score": 20.0,
            "impact_factor": value if verified else None,
            "metric_year": metric_year,
            "source": source,
            "status": status,
            "warning": (
                "Impact factor is not a paper-level scientific quality measure."
                if verified else "A verified impact factor was not supplied."
            ),
        }

    def _composition_evidence(
        self,
        paper: dict[str, Any],
        title: str,
        abstract: str,
    ) -> dict[str, Any]:
        candidates: list[tuple[list[str], dict[str, Any]]] = []
        for assertion in paper.get("assertions", []):
            if not isinstance(assertion, dict) or assertion.get("kind") != "element_set":
                continue
            if assertion.get("inferred") or assertion.get("evidence_level") != "explicit":
                continue
            values = assertion.get("value", [])
            values = values if isinstance(values, list) else [values]
            elements = self._normalize_elements(values)
            for evidence in assertion.get("evidence", []):
                if not isinstance(evidence, dict):
                    continue
                quote = str(evidence.get("quote", "") or "").strip()
                if quote and self._quote_is_present(quote, title, abstract):
                    candidates.append((elements, {
                        "quote": quote,
                        "source": evidence.get("source", "abstract"),
                        "method": "validated_assertion",
                    }))

        for source, text in (("title", title), ("abstract", abstract)):
            for sentence in self._sentences(text):
                elements = self._elements_in_text(sentence)
                if len(elements) in {4, 5}:
                    candidates.append((elements, {
                        "quote": sentence,
                        "source": source,
                        "method": "deterministic_text_detection",
                    }))

        # The workbook's structured composition is useful for recall, but it
        # is not promoted to primary text evidence when its context was
        # machine-derived or no supporting quote is available.
        structured = self._normalize_elements(
            re.findall(
                r"[A-Z][a-z]?",
                str(paper.get("composition_raw", "") or ""),
            )
        )
        if len(structured) in {4, 5} and not candidates:
            return {
                "elements": structured,
                "quotes": [],
                "source": "structured_database_field",
                "primary_text_evidence": False,
            }

        if not candidates:
            return {"elements": [], "quotes": []}
        candidates.sort(key=lambda item: (-len(item[0]), item[1]["quote"]))
        best_elements = candidates[0][0]
        quotes = [item[1] for item in candidates if item[0] == best_elements]
        return {"elements": best_elements, "quotes": quotes[:3]}

    def _hea_evidence(self, title: str, abstract: str) -> tuple[bool, list[dict[str, Any]]]:
        quotes: list[dict[str, Any]] = []
        for source, text in (("title", title), ("abstract", abstract)):
            for sentence in self._sentences(text):
                if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in self.HEA_PATTERNS):
                    quotes.append({"quote": sentence, "source": source})
        return bool(quotes), quotes[:3]

    @staticmethod
    def _matching_sentences(
        title: str,
        abstract: str,
        terms: tuple[str, ...],
        require_number: bool,
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for source, text in (("title", title), ("abstract", abstract)):
            for sentence in EvidenceQualityEvaluator._sentences(text):
                lowered = sentence.lower()
                if any(term in lowered for term in terms) and (
                    not require_number or re.search(r"\d", sentence)
                ):
                    matches.append({"quote": sentence, "source": source})
        return matches[:3]

    @classmethod
    def _elements_in_text(cls, text: str) -> list[str]:
        pattern = "|".join(sorted(cls.METAL_SYMBOLS, key=len, reverse=True))
        found: list[str] = []
        # HEA compositions are often written as one formula, e.g. CuFeCoNiMn.
        formula_pattern = re.compile(r"(?:[A-Z][a-z]?){4,5}")
        allowed = set(cls.METAL_SYMBOLS)
        for formula in formula_pattern.findall(text):
            tokens = re.findall(r"[A-Z][a-z]?", formula)
            if len(tokens) in {4, 5} and all(token in allowed for token in tokens):
                found.extend(tokens)
        symbol = rf"(?<![A-Za-z])(?:{pattern})(?![a-z])"
        separator = r"(?:\s*[-/;]\s*|\s*,\s*(?:and\s+)?|\s+and\s+)"
        sequence_pattern = re.compile(
            rf"{symbol}(?:{separator}{symbol}){{3,4}}"
        )
        for sequence in sequence_pattern.findall(text):
            tokens = re.findall(
                rf"(?<![A-Za-z])({pattern})(?![a-z])",
                sequence,
            )
            if len(tokens) in {4, 5}:
                found.extend(tokens)
        return list(dict.fromkeys(found))

    @classmethod
    def _normalize_elements(cls, values: list[Any]) -> list[str]:
        allowed = set(cls.METAL_SYMBOLS)
        return list(dict.fromkeys(
            str(value).strip() for value in values if str(value).strip() in allowed
        ))

    @staticmethod
    def _sentences(text: str) -> list[str]:
        return [item.strip() for item in re.split(r"(?<=[.!?。！？])\s*", text) if item.strip()]

    @staticmethod
    def _quote_is_present(quote: str, title: str, abstract: str) -> bool:
        normalized = " ".join(quote.lower().split())
        source = " ".join(f"{title} {abstract}".lower().split())
        return bool(normalized) and normalized in source

    @staticmethod
    def _safe_year(value: Any) -> int | None:
        try:
            year = int(value)
        except (TypeError, ValueError):
            return None
        return year if 1800 <= year <= datetime.now().year + 1 else None

    @staticmethod
    def _normalize_text(value: str) -> str:
        value = re.sub(r"[‐‑‒–—−]", "-", value)
        return " ".join(value.lower().split())

    @staticmethod
    def _reaction_is_direct(searchable: str, reaction_family: str) -> bool:
        aliases = {
            "CO2RR": (r"\bco2rr\b", r"\bco2 reduction\b", r"\bcarbon dioxide reduction\b", r"\bco2 electroreduction\b"),
            "HER": (r"\bher\b", r"\bhydrogen evolution(?: reaction)?\b"),
            "OER": (r"\boer\b", r"\boxygen evolution(?: reaction)?\b"),
            "ORR": (r"\borr\b", r"\boxygen reduction(?: reaction)?\b"),
            "NRR": (r"\bnrr\b", r"\bnitrogen reduction(?: reaction)?\b", r"\belectrochemical ammonia synthesis\b"),
        }
        return any(re.search(pattern, searchable, re.IGNORECASE) for pattern in aliases.get(reaction_family.upper(), ()))

    @staticmethod
    def _product_is_direct(searchable: str, target_product: str) -> bool:
        if not target_product:
            return False
        aliases = {
            "CO": (r"\bco\b", r"\bcarbon monoxide\b"),
            "HCOOH/HCOO-": (r"\bhcooh\b", r"\bhcoo-?\b", r"\bformate\b", r"\bformic acid\b"),
            "HCOO-": (r"\bhcoo-?\b", r"\bformate\b", r"\bformic acid\b"),
            "CH3OH": (r"\bch3oh\b", r"\bmethanol\b"),
            "C2H4": (r"\bc2h4\b", r"\bethylene\b"),
            "H2": (r"\bh2\b", r"\bhydrogen production\b"),
            "O2": (r"\bo2\b", r"\boxygen production\b"),
            "NH3": (r"\bnh3\b", r"\bammonia\b"),
        }
        patterns = aliases.get(target_product, (rf"\b{re.escape(target_product.lower())}\b",))
        return any(re.search(pattern, searchable, re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def _quality_level(
        total_score: float,
        metadata_score: float,
        relevance_score: float,
        claim_score: float,
        hea_composition_eligible: bool,
        is_retracted: bool,
    ) -> str:
        if is_retracted:
            return "D"
        if (
            total_score >= 70
            and metadata_score >= 12
            and relevance_score >= 20
            and claim_score >= 18
            and hea_composition_eligible
        ):
            return "A"
        if total_score >= 50 and metadata_score >= 8 and relevance_score >= 12:
            return "B" if hea_composition_eligible else "C"
        if total_score >= 25:
            return "C"
        return "D"
