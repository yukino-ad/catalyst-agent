from __future__ import annotations

import re
from typing import Any

from tools.literature.normalizer import (
    contains_evidence,
    normalize_elements,
    normalize_intermediate,
    normalize_reaction,
)
from tools.literature.schemas import Assertion, Evidence, PaperRecord
from tools.llm_client import LLMError, OpenAICompatibleClient


class LiteratureExtractor:
    PROMPT_VERSION = "literature-extraction-v3"
    ALLOWED_KINDS = {
        "reaction", "product", "element_set", "intermediate", "pathway",
        "material_family", "performance_metric", "catalytic_claim",
        "stability_claim", "synthesis_method",
    }

    def __init__(self, llm: OpenAICompatibleClient | None = None) -> None:
        self.llm = llm or OpenAICompatibleClient()

    def extract(self, paper: PaperRecord) -> PaperRecord:
        if not paper.abstract:
            paper.summary = "Abstract missing; structured extraction was not run."
            return paper
        value = self.llm.chat_json([
            {"role": "system", "content": (
                "You extract scientific claims only from the supplied title and abstract. "
                "Return valid JSON with summary, assertions, and extraction_limitations. "
                "Each assertion must contain kind, value, evidence_level, confidence, "
                "inferred, and evidence. Allowed kinds: reaction, product, element_set, "
                "intermediate, pathway, material_family, performance_metric, "
                "catalytic_claim, stability_claim, synthesis_method. Evidence must be an "
                "array of objects with quote, source, sentence_index. Every quote must be "
                "verbatim from title or abstract. Do not infer missing metals, ratios, "
                "performance values, conditions, or conclusions. A performance_metric "
                "value should be an object containing name, value, unit, product, "
                "potential, potential_reference when explicitly available."
            )},
            {"role": "user", "content": f"Title: {paper.title}\nAbstract: {paper.abstract}"},
        ], max_tokens=1200, timeout_seconds=45)
        paper.summary = str(value.get("summary", "")).strip()
        paper.assertions = self._validate_assertions(value.get("assertions", []), paper)
        return paper

    def deterministic_extract(self, paper: PaperRecord) -> list[Assertion]:
        assertions: list[Assertion] = []
        sentences = self._sentences(f"{paper.title}. {paper.abstract}")
        for index, sentence in enumerate(sentences):
            source = "title" if sentence.strip(". ") in paper.title else "abstract"
            evidence = [Evidence(sentence, source, index)]
            elements = self._elements(sentence)
            if len(elements) in {4, 5}:
                assertions.append(Assertion(
                    kind="element_set", value=elements, evidence_level="explicit",
                    confidence="high", evidence=evidence,
                ))
            lowered = re.sub(r"[‐‑‒–—−]", "-", sentence.lower())
            reaction = self._reaction_in_text(lowered)
            if reaction:
                assertions.append(Assertion(
                    kind="reaction", value=reaction, evidence_level="explicit",
                    confidence="high", evidence=evidence,
                ))
            if "high-entropy" in lowered or "high entropy" in lowered or re.search(r"\bhea\b", lowered):
                assertions.append(Assertion(
                    kind="material_family", value="high_entropy_alloy",
                    evidence_level="explicit", confidence="high", evidence=evidence,
                ))
        return self._deduplicate(assertions)

    @staticmethod
    def _reaction_in_text(text: str) -> str:
        patterns = {
            "CO2RR": (
                r"\bco\s*2\s*rr\b",
                r"\bco\s*2\s+(?:electro)?reduction\b",
                r"\bcarbon dioxide (?:electro)?reduction\b",
                r"\bco\s*2\s+electroreduction\b",
            ),
            "HER": (r"\bhydrogen evolution(?: reaction)?\b",),
            "OER": (r"\boxygen evolution(?: reaction)?\b",),
            "ORR": (r"\boxygen reduction(?: reaction)?\b",),
            "NRR": (r"\bnitrogen reduction(?: reaction)?\b",),
        }
        for reaction, aliases in patterns.items():
            if any(re.search(alias, text) for alias in aliases):
                return reaction
        return ""

    def _validate_assertions(self, values: Any, paper: PaperRecord) -> list[Assertion]:
        accepted: list[Assertion] = []
        if not isinstance(values, list):
            return accepted
        for value in values:
            if not isinstance(value, dict) or value.get("kind") not in self.ALLOWED_KINDS:
                continue
            assertion = Assertion.from_dict(value)
            assertion.evidence = [
                item for item in assertion.evidence
                if contains_evidence(item.quote, paper.title, paper.abstract)
            ]
            if assertion.evidence_level == "explicit" and not assertion.evidence:
                continue
            if assertion.kind == "reaction" and isinstance(assertion.value, str):
                assertion.value = normalize_reaction(assertion.value) or assertion.value
            elif assertion.kind == "element_set":
                raw = assertion.value if isinstance(assertion.value, list) else [assertion.value]
                assertion.value = normalize_elements(raw)
                if len(assertion.value) not in {4, 5}:
                    continue
            elif assertion.kind == "intermediate":
                raw = assertion.value if isinstance(assertion.value, list) else [assertion.value]
                assertion.value = [normalize_intermediate(str(item)) for item in raw if str(item).strip()]
            elif assertion.kind == "performance_metric":
                if not isinstance(assertion.value, dict):
                    continue
                quote = " ".join(item.quote for item in assertion.evidence)
                raw_number = assertion.value.get("value")
                if raw_number is not None and str(raw_number) not in quote:
                    continue
            assertion.validation_status = "passed"
            accepted.append(assertion)
        return self._deduplicate(accepted)

    @staticmethod
    def _elements(text: str) -> list[str]:
        allowed = {
            "Al", "Co", "Cr", "Cu", "Fe", "Ga", "Ge", "Mn", "Mo", "Ni",
            "Ti", "Zn", "Ag", "Pd", "Pt", "Au", "V", "Nb", "Ta", "W",
            "Ru", "Rh", "Ir", "Re", "Zr", "Hf", "Sc", "Y", "Mg", "Sn",
        }
        result = []
        for formula in re.findall(r"(?:[A-Z][a-z]?){4,5}", text):
            tokens = re.findall(r"[A-Z][a-z]?", formula)
            if len(tokens) in {4, 5} and all(token in allowed for token in tokens):
                result.extend(tokens)
        separated = re.findall(r"\b[A-Z][a-z]?\b", text)
        result.extend(token for token in separated if token in allowed)
        return list(dict.fromkeys(result))

    @staticmethod
    def _sentences(text: str) -> list[str]:
        return [value.strip() for value in re.split(r"(?<=[.!?。！？])\s*", text) if value.strip()]

    @staticmethod
    def _deduplicate(assertions: list[Assertion]) -> list[Assertion]:
        result = []
        seen = set()
        for assertion in assertions:
            key = (assertion.kind, repr(assertion.value), tuple(item.quote for item in assertion.evidence))
            if key not in seen:
                seen.add(key)
                result.append(assertion)
        return result


__all__ = ["LiteratureExtractor", "LLMError"]
