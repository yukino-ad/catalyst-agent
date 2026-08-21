from __future__ import annotations

from typing import Any, Iterable

from app.domain.element_properties import (
    CRUSTAL_ABUNDANCE_PPM,
    DATA_SOURCES,
    DATA_VERSION,
    ELEMENT_HANDLING_SCORE,
    MELTING_POINT_K,
    PRICE_SCORE,
    PROCESS_RISK_PENALTY,
    SAFETY_SCORE,
    SUPPORTED_ELEMENTS,
)


DEFAULT_WEIGHTS = {
    "literature_support": 0.25,
    "constraint_preference": 0.10,
    "element_abundance": 0.15,
    "price": 0.20,
    "toxicity_environment": 0.15,
    "synthesis_difficulty": 0.15,
}


class CandidateEvaluator:
    """对候选组成进行可解释的建模前软评分。"""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
    ) -> None:
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        self._validate_weights()

    def evaluate(
        self,
        candidate: dict[str, Any],
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        """评价一个候选，但不执行淘汰。"""

        composition = self._normalize_composition(
            candidate.get("composition")
        )
        fractions = self._atomic_fractions(composition)
        elements = list(composition)

        literature_score, literature_details = (
            self._literature_support_score(
                elements=elements,
                evidence=constraints.get("evidence", []),
            )
        )

        preference_score, preference_details = (
            self._constraint_preference_score(
                fractions=fractions,
                constraints=constraints,
            )
        )

        abundance_score = self._weighted_element_score(
            fractions=fractions,
            score_table={
                element: self._abundance_to_score(value)
                for element, value
                in CRUSTAL_ABUNDANCE_PPM.items()
            },
        )

        price_score = self._weighted_element_score(
            fractions=fractions,
            score_table=PRICE_SCORE,
        )

        safety_score = self._weighted_element_score(
            fractions=fractions,
            score_table=SAFETY_SCORE,
        )

        synthesis_score, synthesis_details = (
            self._synthesis_score(fractions)
        )

        dimension_scores = {
            "literature_support": literature_score,
            "constraint_preference": preference_score,
            "element_abundance": abundance_score,
            "price": price_score,
            "toxicity_environment": safety_score,
            "synthesis_difficulty": synthesis_score,
        }

        total_score = sum(
            dimension_scores[name] * weight
            for name, weight in self.weights.items()
        )

        highest_risk_elements = sorted(
            elements,
            key=lambda element: SAFETY_SCORE[element],
        )[:2]

        return {
            "schema_version": "c2.0",
            "candidate_id": candidate.get(
                "candidate_id",
                self._fallback_candidate_id(composition),
            ),
            "elements": elements,
            "composition": composition,
            "atomic_fractions": {
                element: self._round(value)
                for element, value in fractions.items()
            },
            "scores": {
                name: self._round(value)
                for name, value in dimension_scores.items()
            },
            "weights": dict(self.weights),
            "total_score": self._round(total_score),
            "details": {
                "literature_support": literature_details,
                "constraint_preference": preference_details,
                "element_abundance": {
                    "method": (
                        "atomic-fraction-weighted abundance category"
                    ),
                    "unit": "score_0_to_100",
                },
                "price": {
                    "method": (
                        "atomic-fraction-weighted fixed cost category"
                    ),
                    "live_market_price": False,
                },
                "toxicity_environment": {
                    "method": (
                        "atomic-fraction-weighted conservative "
                        "element-level safety prior"
                    ),
                    "highest_risk_elements": highest_risk_elements,
                    "warning": (
                        "This does not replace compound-, dust-, "
                        "ion-, or nanoparticle-specific assessment."
                    ),
                },
                "synthesis_difficulty": synthesis_details,
            },
            "data_version": DATA_VERSION,
            "data_sources": DATA_SOURCES,
            "ranking_only": True,
            "eliminated": False,
            "decision": "scored_not_filtered",
            "requires_human_confirmation": True,
        }

    def evaluate_many(
        self,
        candidates: Iterable[dict[str, Any]],
        constraints: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """评价并排序多个候选，不删除任何候选。"""

        results = [
            self.evaluate(candidate, constraints)
            for candidate in candidates
        ]

        results.sort(
            key=lambda result: (
                -result["total_score"],
                result["candidate_id"],
            )
        )

        for rank, result in enumerate(results, start=1):
            result["rank"] = rank

        return results

    def _literature_support_score(
        self,
        elements: list[str],
        evidence: Any,
    ) -> tuple[float, dict[str, Any]]:
        """使用单篇证据的最大元素覆盖率，避免跨论文拼接。"""

        if not isinstance(evidence, list):
            evidence = []

        candidate_set = set(elements)
        best_score = 0.0
        best_record: dict[str, Any] | None = None

        for record in evidence:
            if not isinstance(record, dict):
                continue

            evidence_elements = {
                str(element)
                for element in record.get("elements", [])
                if str(element) in SUPPORTED_ELEMENTS
            }

            if not evidence_elements:
                continue

            overlap = candidate_set & evidence_elements
            score = 100.0 * len(overlap) / len(candidate_set)

            if score > best_score:
                best_score = score
                best_record = {
                    "evidence_id": record.get("evidence_id", ""),
                    "paper_id": record.get("paper_id", ""),
                    "title": record.get("title", ""),
                    "doi": record.get("doi", ""),
                    "matched_elements": sorted(overlap),
                    "evidence_elements": sorted(evidence_elements),
                }

        return best_score, {
            "method": "best_single-paper_element_coverage",
            "best_evidence": best_record,
            "unsupported_is_not_rejected": True,
        }

    def _constraint_preference_score(
        self,
        fractions: dict[str, float],
        constraints: dict[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        space = constraints.get("candidate_space", {})
        preferred = {
            str(element)
            for element in space.get("preferred_elements", [])
        }

        if not preferred:
            return 50.0, {
                "method": "neutral_score_no_preference_available",
                "preferred_elements": [],
                "matched_elements": [],
            }

        matched = [
            element
            for element in fractions
            if element in preferred
        ]
        score = 100.0 * sum(
            fractions[element]
            for element in matched
        )

        return score, {
            "method": "preferred_atomic_fraction",
            "preferred_elements": sorted(preferred),
            "matched_elements": matched,
        }

    def _synthesis_score(
        self,
        fractions: dict[str, float],
    ) -> tuple[float, dict[str, Any]]:
        handling_score = self._weighted_element_score(
            fractions,
            ELEMENT_HANDLING_SCORE,
        )

        melting_points = [
            MELTING_POINT_K[element]
            for element in fractions
        ]
        melting_span = max(melting_points) - min(melting_points)
        melting_span_score = self._melting_span_to_score(
            melting_span
        )

        weighted_penalty = sum(
            fractions[element]
            * PROCESS_RISK_PENALTY[element]
            for element in fractions
        )
        process_score = self._clamp(
            100.0 - 4.0 * weighted_penalty
        )

        total = (
            0.40 * handling_score
            + 0.35 * melting_span_score
            + 0.25 * process_score
        )

        active_risks = {
            element: PROCESS_RISK_PENALTY[element]
            for element in fractions
            if PROCESS_RISK_PENALTY[element] > 0
        }

        return total, {
            "method": {
                "element_handling": 0.40,
                "melting_point_span": 0.35,
                "special_process_risk": 0.25,
            },
            "element_handling_score": self._round(
                handling_score
            ),
            "melting_point_span_k": self._round(
                melting_span
            ),
            "melting_point_span_score": self._round(
                melting_span_score
            ),
            "process_risk_score": self._round(
                process_score
            ),
            "active_process_risks": active_risks,
            "warning": (
                "Rule-based estimate; experimental calibration "
                "is still required."
            ),
        }

    @staticmethod
    def _abundance_to_score(ppm: float) -> float:
        if ppm >= 10000:
            return 100.0
        if ppm >= 1000:
            return 85.0
        if ppm >= 100:
            return 70.0
        if ppm >= 10:
            return 55.0
        if ppm >= 1:
            return 35.0
        if ppm >= 0.01:
            return 20.0
        return 5.0

    @staticmethod
    def _melting_span_to_score(span_k: float) -> float:
        if span_k <= 500:
            return 100.0
        if span_k <= 900:
            return 80.0
        if span_k <= 1300:
            return 60.0
        if span_k <= 1800:
            return 40.0
        return 20.0

    @staticmethod
    def _weighted_element_score(
        fractions: dict[str, float],
        score_table: dict[str, float],
    ) -> float:
        return sum(
            fraction * score_table[element]
            for element, fraction in fractions.items()
        )

    @staticmethod
    def _normalize_composition(
        value: Any,
    ) -> dict[str, int]:
        if not isinstance(value, dict) or not value:
            raise ValueError(
                "candidate.composition must be a non-empty dictionary"
            )

        composition: dict[str, int] = {}

        for raw_element, raw_count in value.items():
            element = str(raw_element).strip()
            if element not in SUPPORTED_ELEMENTS:
                raise ValueError(
                    f"Unsupported candidate element: {element}"
                )

            if isinstance(raw_count, bool):
                raise ValueError(
                    f"Invalid atom count for {element}: {raw_count}"
                )

            try:
                count = int(raw_count)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Invalid atom count for {element}: {raw_count}"
                ) from error

            if count <= 0 or float(raw_count) != count:
                raise ValueError(
                    f"Atom count must be a positive integer: {element}"
                )

            composition[element] = count

        if len(composition) != 5:
            raise ValueError(
                "C2 currently requires exactly five elements"
            )

        if sum(composition.values()) != 32:
            raise ValueError(
                "C2 currently requires a 32-atom composition"
            )

        return composition

    @staticmethod
    def _atomic_fractions(
        composition: dict[str, int],
    ) -> dict[str, float]:
        total = float(sum(composition.values()))
        return {
            element: count / total
            for element, count in composition.items()
        }

    def _validate_weights(self) -> None:
        if set(self.weights) != set(DEFAULT_WEIGHTS):
            raise ValueError(
                "C2 weights must contain exactly six dimensions"
            )

        if any(weight < 0 for weight in self.weights.values()):
            raise ValueError("C2 weights cannot be negative")

        if abs(sum(self.weights.values()) - 1.0) > 1e-9:
            raise ValueError("C2 weights must sum to 1.0")

    @staticmethod
    def _fallback_candidate_id(
        composition: dict[str, int],
    ) -> str:
        return "-".join(
            f"{element}{composition[element]}"
            for element in sorted(composition)
        )

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(100.0, value))

    @staticmethod
    def _round(value: float) -> float:
        return round(float(value), 6)