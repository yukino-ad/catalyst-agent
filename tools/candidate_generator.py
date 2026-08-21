from itertools import combinations


# Keep this pool synchronized with StructureBuilder.SUPPORTED_ELEMENTS.
SUPPORTED_ELEMENTS = [
    "Cu", "Fe", "Co", "Ni", "Cr", "Mo", "Mn", "Ti", "Al", "Zn", "Ga", "Ge",
    "Au", "Ag", "Pt", "Pd",
]
LITERATURE_NOBLE_ELEMENTS = {"Au", "Ag", "Pt", "Pd"}


class CandidateGenerator:
    """Generate five-element candidates that the FCC builder can model."""

    def __init__(self, prefer_elements: list[str] | None = None):
        self.prefer_elements = prefer_elements or SUPPORTED_ELEMENTS.copy()
        unsupported = sorted(set(self.prefer_elements) - set(SUPPORTED_ELEMENTS))
        if unsupported:
            raise ValueError(f"建模模块不支持这些元素: {', '.join(unsupported)}")

    def generate(
        self,
        element_count: int = 5,
        top_k: int = 6,
        evidence_element_sets: list[list[str]] | None = None,
    ) -> list[dict]:
        if element_count != 5:
            raise ValueError("当前 HEA 建模规则只支持五元候选。")

        candidates = []
        for combo in combinations(self.prefer_elements, element_count):
            # The fixed-Cu model requires Cu plus four non-Cu elements.
            if "Cu" not in combo:
                continue
            if sum(element in StructureElementGroups.P_BLOCK for element in combo) > 1:
                continue

            evidence_score, evidence_sources = self._evidence_score(combo, evidence_element_sets or [])
            candidates.append(
                {
                    "formula": "-".join(combo),
                    "elements": list(combo),
                    "score": self._score(combo) + evidence_score,
                    "base_score": self._score(combo),
                    "literature_score": evidence_score,
                    "literature_element_sets": evidence_sources,
                    "reason": self._reason(combo, evidence_score),
                    "generation_mode": "fixed_cu",
                    "composition": self._composition(combo),
                }
            )

        candidates.sort(key=lambda item: (-item["score"], item["formula"]))
        return candidates[:top_k]

    def _score(self, combo: tuple[str, ...]) -> int:
        score = 3  # Every retained candidate contains Cu.
        score += sum(element in {"Fe", "Co", "Ni"} for element in combo)
        score += sum(element in {"Cr", "Mo", "Mn"} for element in combo)
        score += sum(element in StructureElementGroups.P_BLOCK for element in combo)
        return score

    def _reason(self, combo: tuple[str, ...], evidence_score: int = 0) -> str:
        reasons = ["Cu 用于 CO2 活化和 CO 路径"]
        if any(element in {"Fe", "Co", "Ni"} for element in combo):
            reasons.append("Fe/Co/Ni 提供过渡金属活性位")
        if any(element in {"Cr", "Mo", "Mn"} for element in combo):
            reasons.append("Cr/Mo/Mn 用于调节局域配位环境")
        if any(element in StructureElementGroups.P_BLOCK for element in combo):
            reasons.append("仅保留一个 p 区元素以满足建模约束")
        if set(combo) & LITERATURE_NOBLE_ELEMENTS:
            reasons.append("包含文献候选中的 Au/Ag/Pt/Pd")
        if evidence_score:
            reasons.append("元素组合获得本次 RAG 文献证据加分")
        return "；".join(reasons)

    def _composition(self, combo: tuple[str, ...]) -> dict[str, int]:
        composition = {"Cu": 8}
        non_cu = [element for element in combo if element != "Cu"]
        if set(combo) & LITERATURE_NOBLE_ELEMENTS:
            composition.update({element: 6 for element in non_cu})
            return composition
        p_elements = [element for element in non_cu if element in StructureElementGroups.P_BLOCK]
        if p_elements:
            composition[p_elements[0]] = 3
            composition.update({element: 7 for element in non_cu if element not in p_elements})
        else:
            composition.update({element: 6 for element in non_cu})
        return composition

    @staticmethod
    def _evidence_score(
        combo: tuple[str, ...], evidence_element_sets: list[list[str]]
    ) -> tuple[int, list[list[str]]]:
        combo_set = set(combo)
        matched_sources: list[list[str]] = []
        best_overlap = 0
        exact_match = False
        for elements in evidence_element_sets:
            normalized = list(dict.fromkeys(str(element).strip().capitalize() for element in elements))
            supported = set(normalized) & set(SUPPORTED_ELEMENTS)
            overlap = len(combo_set & supported)
            if overlap:
                matched_sources.append(normalized)
                best_overlap = max(best_overlap, overlap)
            if supported == combo_set:
                exact_match = True
        return (20 if exact_match else best_overlap * 2), matched_sources


class StructureElementGroups:
    P_BLOCK = {"Al", "Zn", "Ga", "Ge"}
