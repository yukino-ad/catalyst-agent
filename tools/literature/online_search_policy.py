from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any


class OnlineSearchPolicy:
    """
    判断本地文献证据是否足够，以及是否需要联网检索。

    本类只做决策，不执行任何网络请求。

    它不会：
    1. 调用 OpenAlex；
    2. 调用 LLM；
    3. 修改本地数据库；
    4. 删除 sample 记录；
    5. 判断论文结论绝对正确。

    它只根据 B2 返回的本地检索结果，
    判断是否应该进入后续 B4 联网检索。
    """

    def __init__(
        self,
        minimum_real_papers: int = 5,
        minimum_unique_papers: int = 3,
        minimum_a_level_papers: int = 2,
        minimum_reaction_direct_papers: int = 2,
        recent_year_window: int = 5,
    ) -> None:
        """
        初始化联网触发阈值。

        minimum_real_papers:
            至少需要多少条非 sample 的真实论文记录。

        minimum_unique_papers:
            按 DOI 或规范化标题估算后，
            至少需要多少项独立研究。

        minimum_a_level_papers:
            至少需要多少篇 B1 A 级记录。

        minimum_reaction_direct_papers:
            至少需要多少篇标题或摘要直接涉及目标反应的论文。

        recent_year_window:
            最近多少年以内的论文视作近期论文。
        """

        if minimum_real_papers <= 0:
            raise ValueError(
                "minimum_real_papers 必须大于 0。"
            )

        if minimum_unique_papers <= 0:
            raise ValueError(
                "minimum_unique_papers 必须大于 0。"
            )

        if minimum_a_level_papers < 0:
            raise ValueError(
                "minimum_a_level_papers 不能小于 0。"
            )

        if minimum_reaction_direct_papers < 0:
            raise ValueError(
                "minimum_reaction_direct_papers 不能小于 0。"
            )

        if recent_year_window <= 0:
            raise ValueError(
                "recent_year_window 必须大于 0。"
            )

        self.minimum_real_papers = (
            minimum_real_papers
        )
        self.minimum_unique_papers = (
            minimum_unique_papers
        )
        self.minimum_a_level_papers = (
            minimum_a_level_papers
        )
        self.minimum_reaction_direct_papers = (
            minimum_reaction_direct_papers
        )
        self.recent_year_window = (
            recent_year_window
        )

    def evaluate(
        self,
        local_result: dict[str, Any],
        task_analysis: dict[str, Any] | None = None,
        question: str = "",
    ) -> dict[str, Any]:
        """
        评价 B2 本地检索结果，并决定是否联网。

        参数：
        local_result:
            LocalLiteratureRetriever.retrieve()
            返回的完整结果。

        task_analysis:
            A2 TaskAnalyzer 返回的任务分析。

        question:
            用户原始自然语言问题。
        """

        task_analysis = task_analysis or {}
        question = question.strip()

        selected = local_result.get(
            "selected",
            [],
        )

        if not isinstance(selected, list):
            selected = []

        selected = [
            paper
            for paper in selected
            if isinstance(paper, dict)
        ]

        explicit_local_only = (
            self._requests_local_only(question)
        )

        explicit_latest = (
            self._requests_latest_literature(
                question
            )
        )

        online_preference = str(
            task_analysis.get(
                "online_preference",
                "auto",
            )
            or "auto"
        ).strip().lower()
        if online_preference not in {
            "auto",
            "required",
            "forbidden",
        }:
            online_preference = "auto"

        development_samples = [
            paper
            for paper in selected
            if self._is_development_sample(
                paper
            )
        ]

        real_papers = [
            paper
            for paper in selected
            if not self._is_development_sample(
                paper
            )
        ]

        unique_real_papers = (
            self._unique_papers(
                real_papers
            )
        )

        a_level_papers = [
            paper
            for paper in real_papers
            if self._quality_level(paper) == "A"
        ]

        ab_level_papers = [
            paper
            for paper in real_papers
            if self._quality_level(paper)
            in {"A", "B"}
        ]

        reaction_direct_papers = [
            paper
            for paper in real_papers
            if self._quality_flag(
                paper,
                "reaction_direct",
            )
        ]

        # 这里只统计“词法提及”。
        # 不能解释成论文证明了目标产物。
        product_mention_papers = [
            paper
            for paper in real_papers
            if self._quality_flag(
                paper,
                "product_direct",
            )
        ]

        recent_papers = [
            paper
            for paper in real_papers
            if self._is_recent(paper)
        ]

        reasons: list[str] = []

        if len(real_papers) < (
            self.minimum_real_papers
        ):
            reasons.append(
                "真实论文少于 "
                f"{self.minimum_real_papers} 篇"
            )

        if len(unique_real_papers) < (
            self.minimum_unique_papers
        ):
            reasons.append(
                "按 DOI 或规范化标题估算后，"
                "独立论文少于 "
                f"{self.minimum_unique_papers} 篇"
            )

        if len(a_level_papers) < (
            self.minimum_a_level_papers
        ):
            reasons.append(
                "B1 A 级元数据与相关性证据少于 "
                f"{self.minimum_a_level_papers} 篇"
            )

        if len(reaction_direct_papers) < (
            self.minimum_reaction_direct_papers
        ):
            reasons.append(
                "标题或摘要直接涉及目标反应的论文少于 "
                f"{self.minimum_reaction_direct_papers} 篇"
            )

        if explicit_latest:
            reasons.append(
                "用户明确要求最新、近期或联网文献"
            )

        if online_preference == "required":
            reasons.append(
                "A 阶段规范任务要求联网检索"
            )

        if (
            explicit_latest
            and not recent_papers
        ):
            reasons.append(
                "本地结果中没有足够的近期论文"
            )

        if not selected:
            reasons.append(
                "本地检索没有返回任何候选论文"
            )

        if (
            selected
            and len(development_samples)
            == len(selected)
        ):
            reasons.append(
                "本地结果全部是开发示例记录"
            )

        # Local evidence is the default. Online search only fills a measured
        # evidence gap or responds to an explicit freshness/online request.
        use_online_search = bool(reasons)
        decision = "online_supplement" if use_online_search else "local_sufficient"

        # 用户明确要求仅使用本地文献时，
        # 禁止联网，但仍然保留证据不足的原因。
        if explicit_local_only or online_preference == "forbidden":
            use_online_search = False
            decision = "online_forbidden_by_user"

        reaction_family = str(
            task_analysis.get(
                "reaction_family",
                "",
            )
            or ""
        ).strip()

        target_product = str(
            task_analysis.get(
                "target_product",
                "",
            )
            or ""
        ).strip()

        warnings: list[str] = []

        if development_samples:
            warnings.append(
                "sample:* 开发示例不计入真实论文数量，"
                "也不应作为正式科研结论依据。"
            )

        if product_mention_papers:
            warnings.append(
                "product_mention_count 只表示标题或摘要"
                "在词法上提到目标产物，不表示论文已经证明"
                "该产物是最终选择性产物。"
            )

        if (
            (explicit_local_only or online_preference == "forbidden")
            and reasons
        ):
            warnings.append(
                "本地证据可能不足，但用户明确禁止联网；"
                "系统将保留证据缺口并继续使用本地结果。"
            )

        return {
            "use_online_search": (
                use_online_search
            ),
            "decision": decision,
            "reasons": reasons,
            "warnings": warnings,
            "query_context": {
                "question": question,
                "reaction_family": (
                    reaction_family
                ),
                "target_product": (
                    target_product
                ),
                "explicit_latest_request": (
                    explicit_latest
                ),
                "explicit_local_only": (
                    explicit_local_only
                ),
                "online_preference": online_preference,
            },
            "metrics": {
                "selected_count": len(
                    selected
                ),
                "development_sample_count": len(
                    development_samples
                ),
                "real_paper_count": len(
                    real_papers
                ),
                "unique_real_paper_count": len(
                    unique_real_papers
                ),
                "potential_duplicate_count": (
                    len(real_papers)
                    - len(unique_real_papers)
                ),
                "a_level_count": len(
                    a_level_papers
                ),
                "ab_level_count": len(
                    ab_level_papers
                ),
                "reaction_direct_count": len(
                    reaction_direct_papers
                ),
                "product_mention_count": len(
                    product_mention_papers
                ),
                "recent_paper_count": len(
                    recent_papers
                ),
            },
            "thresholds": {
                "minimum_real_papers": (
                    self.minimum_real_papers
                ),
                "minimum_unique_papers": (
                    self.minimum_unique_papers
                ),
                "minimum_a_level_papers": (
                    self.minimum_a_level_papers
                ),
                "minimum_reaction_direct_papers": (
                    self.minimum_reaction_direct_papers
                ),
                "recent_year_window": (
                    self.recent_year_window
                ),
            },
            "online_budget": {
                "max_queries": 2 if (explicit_latest or online_preference == "required") else 1,
                "per_page": 5,
                "reason": "local_first_with_small_online_gap_fill",
            },
            "real_paper_ids": [
                str(
                    paper.get(
                        "paper_id",
                        "",
                    )
                )
                for paper in real_papers
            ],
            "unique_paper_ids": [
                str(
                    paper.get(
                        "paper_id",
                        "",
                    )
                )
                for paper in unique_real_papers
            ],
        }

    @staticmethod
    def _is_development_sample(
        paper: dict[str, Any],
    ) -> bool:
        """
        判断是否为开发示例。

        当前项目中的示例记录通常满足：
        paper_id 以 sample: 开头，
        或 source 等于 sample。
        """

        paper_id = str(
            paper.get("paper_id", "")
            or ""
        ).strip().lower()

        source = str(
            paper.get("source", "")
            or ""
        ).strip().lower()

        return (
            paper_id.startswith("sample:")
            or source == "sample"
        )

    @staticmethod
    def _quality_level(
        paper: dict[str, Any],
    ) -> str:
        quality = paper.get(
            "evidence_quality",
            {},
        )

        if not isinstance(quality, dict):
            return "D"

        level = str(
            quality.get(
                "quality_level",
                "D",
            )
        ).strip().upper()

        if level not in {
            "A",
            "B",
            "C",
            "D",
        }:
            return "D"

        return level

    @staticmethod
    def _quality_flag(
        paper: dict[str, Any],
        field: str,
    ) -> bool:
        quality = paper.get(
            "evidence_quality",
            {},
        )

        if not isinstance(quality, dict):
            return False

        return bool(
            quality.get(field, False)
        )

    def _is_recent(
        self,
        paper: dict[str, Any],
    ) -> bool:
        try:
            year = int(
                paper.get("year")
            )
        except (TypeError, ValueError):
            return False

        current_year = (
            datetime.now().year
        )

        minimum_year = (
            current_year
            - self.recent_year_window
            + 1
        )

        return (
            minimum_year
            <= year
            <= current_year + 1
        )

    def _unique_papers(
        self,
        papers: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        对本地证据进行轻量级去重估算。

        优先使用 DOI。
        DOI 缺失时使用规范化标题。

        B3 只做联网决策所需的近似去重；
        B5 会实现正式的版本合并与去重。
        """

        unique: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for paper in papers:
            key = self._paper_identity(
                paper
            )

            if key in seen_keys:
                continue

            seen_keys.add(key)
            unique.append(paper)

        return unique

    def _paper_identity(
        self,
        paper: dict[str, Any],
    ) -> str:
        doi = self._normalize_doi(
            paper.get("doi", "")
        )

        if doi:
            return f"doi:{doi}"

        title = self._normalize_title(
            paper.get("title", "")
        )

        if title:
            return f"title:{title}"

        paper_id = str(
            paper.get("paper_id", "")
            or ""
        ).strip().lower()

        if paper_id:
            return f"id:{paper_id}"

        # 极端情况下使用对象内容，
        # 防止所有无标识记录错误合并成一条。
        return f"unknown:{id(paper)}"

    @staticmethod
    def _normalize_doi(
        value: Any,
    ) -> str:
        doi = str(
            value or ""
        ).strip().lower()

        prefixes = (
            "https://doi.org/",
            "http://doi.org/",
            "doi:",
        )

        for prefix in prefixes:
            if doi.startswith(prefix):
                doi = doi[len(prefix):]

        return doi.strip()

    @staticmethod
    def _normalize_title(
        value: Any,
    ) -> str:
        title = html.unescape(
            str(value or "")
        )

        # 删除 OpenAlex 标题中的 HTML 标签，
        # 例如 <sub>2</sub>。
        title = re.sub(
            r"<[^>]+>",
            "",
            title,
        )

        title = title.lower()

        # 只保留字母和数字，减少标点差异。
        title = re.sub(
            r"[^a-z0-9]+",
            " ",
            title,
        )

        return " ".join(
            title.split()
        )

    @staticmethod
    def _requests_latest_literature(
        question: str,
    ) -> bool:
        text = question.lower()

        terms = (
            "最新",
            "近期",
            "最近研究",
            "最新进展",
            "联网检索",
            "在线检索",
            "latest",
            "recent literature",
            "recent studies",
            "state of the art",
            "online search",
        )

        return any(
            term in text
            for term in terms
        )

    @staticmethod
    def _requests_local_only(
        question: str,
    ) -> bool:
        text = question.lower()

        terms = (
            "只用本地",
            "仅使用本地",
            "不要联网",
            "不联网",
            "禁止联网",
            "local only",
            "offline only",
            "do not search online",
        )

        return any(
            term in text
            for term in terms
        )
