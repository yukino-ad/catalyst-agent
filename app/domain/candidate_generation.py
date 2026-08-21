from __future__ import annotations

import hashlib
from itertools import combinations
from typing import Any, Iterable

from app.domain.candidate_constraints import (
    CandidateConstraintBuilder,
    P_BLOCK_ELEMENTS,
)


class ConstraintDrivenCandidateGenerator:
    """根据 C1 硬约束生成五元、32 原子候选组成。"""

    def __init__(
        self,
        constraint_builder: CandidateConstraintBuilder | None = None,
    ) -> None:
        self.constraint_builder = (
            constraint_builder or CandidateConstraintBuilder()
        )

    def generate(
        self,
        constraints: dict[str, Any],
        variants_per_combination: int = 1,
        max_candidates: int | None = None,
        fixed_composition_variants: bool = False,
    ) -> dict[str, Any]:
        """
        生成合法候选池。

        C3 只应用硬约束，不进行软评分，也不淘汰低分候选。
        """

        self._validate_options(
            variants_per_combination=variants_per_combination,
            max_candidates=max_candidates,
        )
        self.constraint_builder.validate(constraints)

        candidate_space = constraints.get("candidate_space", {})
        structure_rules = constraints.get("structure_rules", {})

        element_count = int(
            candidate_space.get("element_count", 5)
        )
        allowed_elements = self._normalize_elements(
            candidate_space.get("allowed_elements", [])
        )
        required_elements = set(
            self._normalize_elements(
                candidate_space.get("required_elements", [])
            )
        )
        excluded_elements = set(
            self._normalize_elements(
                candidate_space.get("excluded_elements", [])
            )
        )
        preferred_elements = set(
            self._normalize_elements(
                candidate_space.get("preferred_elements", [])
            )
        )

        if element_count != 5:
            raise ValueError(
                "C3 currently supports exactly five-element candidates"
            )

        if not allowed_elements:
            raise ValueError(
                "constraints.candidate_space.allowed_elements is empty"
            )

        if required_elements - set(allowed_elements):
            raise ValueError(
                "Every required element must belong to allowed_elements"
            )

        if excluded_elements & set(allowed_elements):
            raise ValueError(
                "Excluded elements must not remain in allowed_elements"
            )

        generated: list[dict[str, Any]] = []
        rejected_counts = {
            "missing_required_element": 0,
            "too_many_p_block_elements": 0,
        }

        legal_combination_count = 0

        for combo in combinations(allowed_elements, element_count):
            combo_set = set(combo)

            if not required_elements <= combo_set:
                rejected_counts["missing_required_element"] += 1
                continue

            p_block_count = len(
                combo_set & P_BLOCK_ELEMENTS
            )
            max_p_block = int(
                structure_rules.get(
                    "max_p_block_elements",
                    1,
                )
            )

            if p_block_count > max_p_block:
                rejected_counts[
                    "too_many_p_block_elements"
                ] += 1
                continue

            legal_combination_count += 1

            variant_count = (
                variants_per_combination
                if (
                    fixed_composition_variants
                    or (
                        "Cu" not in combo_set
                        and p_block_count == 0
                    )
                )
                else 1
            )

            for variant_index in range(variant_count):
                composition = (
                    self.constraint_builder.build_composition(
                        list(combo),
                        variant_index=variant_index,
                    )
                )

                candidate = self._build_candidate(
                    elements=list(combo),
                    composition=composition,
                    variant_index=variant_index,
                    preferred_elements=preferred_elements,
                    required_elements=required_elements,
                )
                generated.append(candidate)

                if (
                    max_candidates is not None
                    and len(generated) >= max_candidates
                ):
                    return self._result(
                        candidates=generated,
                        legal_combination_count=(
                            legal_combination_count
                        ),
                        rejected_counts=rejected_counts,
                        variants_per_combination=(
                            variants_per_combination
                        ),
                        max_candidates=max_candidates,
                        truncated=True,
                    )

        return self._result(
            candidates=generated,
            legal_combination_count=legal_combination_count,
            rejected_counts=rejected_counts,
            variants_per_combination=variants_per_combination,
            max_candidates=max_candidates,
            truncated=False,
        )

    def generate_and_score(
        self,
        constraints: dict[str, Any],
        evaluator: Any,
        variants_per_combination: int = 1,
        max_candidates: int | None = None,
        fixed_composition_variants: bool = False,
    ) -> dict[str, Any]:
        """
        生成后调用 C2 评分。

        evaluator 只要求提供 evaluate_many()，因此以后可被
        LangGraph Service 或测试替身替换。
        """

        generation_result = self.generate(
            constraints=constraints,
            variants_per_combination=variants_per_combination,
            max_candidates=max_candidates,
            fixed_composition_variants=fixed_composition_variants,
        )

        ranked = evaluator.evaluate_many(
            generation_result["candidates"],
            constraints,
        )

        return {
            **generation_result,
            "candidates": ranked,
            "scoring_applied": True,
            "scoring_stage": "c2",
            "candidate_count": len(ranked),
        }

    def _build_candidate(
        self,
        elements: list[str],
        composition: dict[str, int],
        variant_index: int,
        preferred_elements: set[str],
        required_elements: set[str],
    ) -> dict[str, Any]:
        candidate_id = self._candidate_id(
            composition=composition,
            variant_index=variant_index,
        )

        matched_preferred = [
            element
            for element in elements
            if element in preferred_elements
        ]
        matched_required = [
            element
            for element in elements
            if element in required_elements
        ]

        p_block_elements = [
            element
            for element in elements
            if element in P_BLOCK_ELEMENTS
        ]

        return {
            "schema_version": "c3.0",
            "candidate_id": candidate_id,
            "formula": "-".join(elements),
            "elements": elements,
            "composition": composition,
            "total_atoms": sum(composition.values()),
            "variant_index": variant_index,
            "contains_cu": "Cu" in elements,
            "p_block_elements": p_block_elements,
            "matched_required_elements": matched_required,
            "matched_preferred_elements": matched_preferred,
            "generation": {
                "stage": "c3",
                "method": (
                    "constraint_driven_combinatorial_generation"
                ),
                "hard_constraints_applied": [
                    "exactly_five_elements",
                    "allowed_elements_only",
                    "required_elements_included",
                    "excluded_elements_removed",
                    "maximum_one_p_block_element",
                    "c1_32_atom_composition_rule",
                ],
            },
            "ranking_only": True,
            "eliminated": False,
            "decision": "generated_not_filtered",
        }

    @staticmethod
    def _candidate_id(
        composition: dict[str, int],
        variant_index: int,
    ) -> str:
        composition_text = "-".join(
            f"{element}{composition[element]}"
            for element in sorted(composition)
        )
        payload = f"{composition_text}|variant={variant_index}"
        digest = hashlib.sha256(
            payload.encode("ascii")
        ).hexdigest()[:10]

        return f"c3-{composition_text}-{digest}"

    @staticmethod
    def _normalize_elements(
        values: Iterable[Any],
    ) -> list[str]:
        if isinstance(values, str):
            values = values.split(",")

        result: list[str] = []

        for value in values:
            raw = str(value).strip()
            if not raw:
                continue

            symbol = (
                raw[0].upper()
                + raw[1:].lower()
            )

            if symbol not in result:
                result.append(symbol)

        return result

    @staticmethod
    def _validate_options(
        variants_per_combination: int,
        max_candidates: int | None,
    ) -> None:
        if isinstance(variants_per_combination, bool):
            raise ValueError(
                "variants_per_combination must be an integer"
            )

        if not isinstance(variants_per_combination, int):
            raise ValueError(
                "variants_per_combination must be an integer"
            )

        if not 1 <= variants_per_combination <= 5:
            raise ValueError(
                "variants_per_combination must be between 1 and 5"
            )

        if max_candidates is not None:
            if isinstance(max_candidates, bool):
                raise ValueError(
                    "max_candidates must be a positive integer"
                )

            if (
                not isinstance(max_candidates, int)
                or max_candidates <= 0
            ):
                raise ValueError(
                    "max_candidates must be a positive integer"
                )

    @staticmethod
    def _result(
        candidates: list[dict[str, Any]],
        legal_combination_count: int,
        rejected_counts: dict[str, int],
        variants_per_combination: int,
        max_candidates: int | None,
        truncated: bool,
    ) -> dict[str, Any]:
        return {
            "schema_version": "c3.0",
            "generation_stage": "c3",
            "candidate_count": len(candidates),
            "legal_combination_count": legal_combination_count,
            "rejected_counts": rejected_counts,
            "variants_per_combination": (
                variants_per_combination
            ),
            "max_candidates": max_candidates,
            "truncated": truncated,
            "scoring_applied": False,
            "candidates": candidates,
            "warnings": (
                [
                    "Candidate generation stopped at "
                    f"max_candidates={max_candidates}."
                ]
                if truncated
                else []
            ),
        }
