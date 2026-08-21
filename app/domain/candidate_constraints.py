from __future__ import annotations

from typing import Any


MODEL_SUPPORTED_ELEMENTS = (
    "Cu", "Fe", "Co", "Ni", "Cr", "Mo", "Mn", "Ti",
    "Al", "Zn", "Ga", "Ge", "Au", "Ag", "Pt", "Pd",
)

P_BLOCK_ELEMENTS = {
    "Al", "Zn", "Ga", "Ge",
}


class CandidateConstraintBuilder:
    """将任务、文献证据和用户要求转换为候选设计约束。"""

    def build(
        self,
        task_analysis: dict[str, Any],
        accepted_papers: list[dict[str, Any]] | None = None,
        user_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(task_analysis, dict):
            raise TypeError("task_analysis 必须是字典。")

        accepted_papers = accepted_papers or []
        user_overrides = user_overrides or {}

        if not isinstance(accepted_papers, list):
            raise TypeError("accepted_papers 必须是列表。")

        if not isinstance(user_overrides, dict):
            raise TypeError("user_overrides 必须是字典。")

        direct_elements, inferred_elements, evidence = (
            self._literature_elements(accepted_papers)
        )

        # 只有用户明确列入 required_elements 的元素才是硬约束。
        required = self._elements(
            user_overrides.get("required_elements", [])
        )
        user_preferred = self._elements(
            user_overrides.get("preferred_elements", [])
        )
        excluded = self._elements(
            user_overrides.get("excluded_elements", [])
        )

        conflicts = sorted(set(required) & set(excluded))
        if conflicts:
            raise ValueError(
                "元素不能同时为必选和禁用："
                + ", ".join(conflicts)
            )

        allowed = [
            element
            for element in MODEL_SUPPORTED_ELEMENTS
            if element not in excluded
        ]

        if len(required) > 5:
            raise ValueError(
                "当前五元模型最多只能指定 5 个必选元素。"
            )

        # 文献明确提到的元素只进入 preferred，不升级为 required。
        preferred = self._unique([
            *user_preferred,
            *direct_elements,
        ])
        preferred = [
            element
            for element in preferred
            if element in allowed and element not in required
        ]

        inferred = [
            element
            for element in inferred_elements
            if (
                element in allowed
                and element not in required
                and element not in preferred
            )
        ]

        warnings: list[str] = []

        required_source = str(
            user_overrides.get("required_elements_source", "") or ""
        )
        if required_source == "explicit_direct_c_request" and len(required) == 5:
            warnings.append(
                "该五元组成由用户明确指定，作为理想建模假设进入 C 阶段。"
            )
        elif not direct_elements:
            warnings.append(
                "人工接受的论文中暂未找到明确的元素集合；"
                "C3 不应把 LLM 推断元素当作文献事实。"
            )

        if inferred:
            warnings.append(
                "存在推断元素，但它们不会自动进入优先元素；"
                "需要人工确认后才能升级为设计约束。"
            )

        constraints = {
            "schema_version": "c1.1",
            "reaction": {
                "reaction_id": task_analysis.get(
                    "reaction_id", "UNKNOWN"
                ),
                "reaction_family": task_analysis.get(
                    "reaction_family", "UNKNOWN"
                ),
                "target_product": task_analysis.get(
                    "target_product"
                ),
                "material_family": task_analysis.get(
                    "material_family", ""
                ),
            },
            "candidate_space": {
                "element_count": 5,
                "required_elements": required,
                "preferred_elements": preferred,
                "inferred_elements_pending_review": inferred,
                "excluded_elements": excluded,
                "allowed_elements": allowed,
                "model_supported_elements": list(
                    MODEL_SUPPORTED_ELEMENTS
                ),
            },
            "structure_rules": {
                "crystal_structure": "FCC",
                "supercell": "2x2x2",
                "total_atoms": 32,
                "generation_mode": "composition_rule_v2",
                "cu_atoms_when_present": 8,
                "max_p_block_elements": 1,
                "p_block_elements": sorted(P_BLOCK_ELEMENTS),
                "composition_rules": {
                    "with_cu_with_p_block": (
                        "Cu=8，p 区元素=3，其余三种元素各 7"
                    ),
                    "with_cu_without_p_block": (
                        "Cu=8，其余四种元素各 6"
                    ),
                    "without_cu_with_p_block": (
                        "p 区元素=4，其余四种元素各 7"
                    ),
                    "without_cu_without_p_block": (
                        "近等比例 7,7,6,6,6；通过 variant_index "
                        "确定性轮换两个 7 原子元素"
                    ),
                },
                "lattice_rule": "Vegard",
            },
            "evaluation_dimensions": {
                "literature_support": "c2",
                "constraint_preference": "c2",
                "element_abundance": "c2",
                "price": "c2",
                "toxicity_environment": "c2",
                "synthesis_difficulty": "c2",
            },
            "deferred_post_structure_evaluation": {
                "formation_energy": "c6",
                "cgcnn_domain": "c6",
                "atomic_size_delta": "c7",
                "omega": "c7",
                "binary_mixing_enthalpy": "c7_input_only",
            },
            "evidence": evidence,
            "assumptions": [
                {
                    "id": "A1",
                    "statement": (
                        "当前结构建模使用五元 FCC 2x2x2、"
                        "总计 32 原子的组成规则。"
                    ),
                    "source": "current_model_rule",
                    "requires_review": True,
                },
                {
                    "id": "A2",
                    "statement": (
                        "Cu 仅在用户明确要求时成为必选元素；"
                        "文献提及 Cu 只构成优先证据。"
                    ),
                    "source": "c1.1_design_rule",
                    "requires_review": False,
                },
            ],
            "warnings": warnings,
            "requires_human_confirmation": True,
        }

        self.validate(constraints)
        return constraints

    def build_composition(
        self,
        elements: list[str],
        variant_index: int = 0,
    ) -> dict[str, int]:
        """按照 C1.1 规则为五元候选生成 32 原子组成。"""

        normalized = self._elements(elements)

        if len(normalized) != 5:
            raise ValueError("组成规则要求恰好 5 种不同元素。")

        p_elements = [
            element
            for element in normalized
            if element in P_BLOCK_ELEMENTS
        ]

        if len(p_elements) > 1:
            raise ValueError("候选中最多只能包含一个 p 区元素。")

        has_cu = "Cu" in normalized

        if has_cu and p_elements:
            p_element = p_elements[0]
            composition = {"Cu": 8, p_element: 3}
            composition.update({
                element: 7
                for element in normalized
                if element not in {"Cu", p_element}
            })
            return self._ordered_composition(normalized, composition)

        if has_cu:
            composition = {"Cu": 8}
            composition.update({
                element: 6
                for element in normalized
                if element != "Cu"
            })
            return self._ordered_composition(normalized, composition)

        if p_elements:
            p_element = p_elements[0]
            composition = {
                element: (4 if element == p_element else 7)
                for element in normalized
            }
            return composition

        # 32 不能被 5 整除。轮换选择连续两个元素占 7 个，
        # 其余三个元素各占 6 个，便于 C3 生成不同近等原子变体。
        offset = int(variant_index) % len(normalized)
        enriched = {
            normalized[offset],
            normalized[(offset + 1) % len(normalized)],
        }
        return {
            element: (7 if element in enriched else 6)
            for element in normalized
        }

    def validate(self, constraints: dict[str, Any]) -> None:
        """检查约束内部是否自相矛盾。"""

        space = constraints.get("candidate_space", {})
        required = set(space.get("required_elements", []))
        preferred = set(space.get("preferred_elements", []))
        excluded = set(space.get("excluded_elements", []))
        allowed = set(space.get("allowed_elements", []))

        if not required <= allowed:
            raise ValueError("必选元素必须属于允许元素集合。")

        if required & excluded:
            raise ValueError("必选元素不能同时被禁用。")

        if preferred & excluded:
            raise ValueError("优先元素不能同时被禁用。")

        element_count = int(space.get("element_count", 0))
        if element_count != 5:
            raise ValueError("当前建模流程只支持五元候选。")

        if len(required) > element_count:
            raise ValueError("必选元素数量超过候选元素总数。")

    def _literature_elements(
        self,
        papers: list[dict[str, Any]],
    ) -> tuple[list[str], list[str], list[dict[str, Any]]]:
        direct: list[str] = []
        inferred: list[str] = []
        evidence: list[dict[str, Any]] = []

        for paper in papers:
            if not isinstance(paper, dict):
                continue

            if paper.get("review_status") not in {
                None, "", "accepted"
            }:
                continue

            evidence_id = str(paper.get("evidence_id", "") or "")
            legacy_elements = self._elements(
                paper.get("elements", [])
            )

            if legacy_elements:
                direct.extend(legacy_elements)
                evidence.append(self._evidence_record(
                    paper,
                    evidence_id,
                    legacy_elements,
                    "explicit_element_set",
                    "elements",
                ))

            assertions = paper.get("assertions", [])
            if not isinstance(assertions, list):
                continue

            for assertion in assertions:
                if not isinstance(assertion, dict):
                    continue
                if assertion.get("kind") != "element_set":
                    continue

                elements = self._elements(assertion.get("value", []))
                if not elements:
                    continue

                is_inferred = assertion.get("inferred") is True or (
                    assertion.get("evidence_level") == "inferred"
                )
                target = inferred if is_inferred else direct
                target.extend(elements)

                evidence.append(self._evidence_record(
                    paper,
                    evidence_id,
                    elements,
                    (
                        "inferred_element_set"
                        if is_inferred
                        else "explicit_element_set"
                    ),
                    "assertions",
                ))

        return (
            self._unique(direct),
            self._unique(inferred),
            evidence,
        )

    @staticmethod
    def _evidence_record(
        paper: dict[str, Any],
        evidence_id: str,
        elements: list[str],
        claim_type: str,
        source_field: str,
    ) -> dict[str, Any]:
        return {
            "evidence_id": evidence_id,
            "paper_id": paper.get("paper_id", ""),
            "title": paper.get("title", ""),
            "doi": paper.get("doi", ""),
            "claim_type": claim_type,
            "elements": elements,
            "source_field": source_field,
        }

    @staticmethod
    def _ordered_composition(
        elements: list[str],
        values: dict[str, int],
    ) -> dict[str, int]:
        return {element: values[element] for element in elements}

    @staticmethod
    def _elements(value: Any) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            value = value.replace("，", ",").split(",")

        if not isinstance(value, (list, tuple, set)):
            raise TypeError("元素字段必须是列表或逗号分隔字符串。")

        result: list[str] = []
        for item in value:
            raw = str(item).strip()
            if not raw:
                continue

            symbol = raw[0].upper() + raw[1:].lower()
            if symbol not in MODEL_SUPPORTED_ELEMENTS:
                raise ValueError(f"当前模型不支持元素：{symbol}")

            if symbol not in result:
                result.append(symbol)

        return result

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            if value not in result:
                result.append(value)
        return result
