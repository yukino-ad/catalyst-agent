from __future__ import annotations

from typing import Any

from tools.literature.repository import (
    LiteratureRepository,
)
from tools.literature.schemas import PaperRecord
from tools.literature.retry_support import literature_verification_level


class LiteratureReviewGate:
    """
    对 B5 产生的文献证据执行人工审查和受控入库。

    本类负责：
    1. 校验 accept、reject、defer 决定；
    2. 防止同一证据进入多个分类；
    3. 将未明确分类的证据自动设为 defer；
    4. 只允许接受的纯在线论文写入数据库；
    5. 防止通过 paper_id 或 DOI 重复写入。

    本类不会：
    1. 调用 LLM；
    2. 访问网络；
    3. 自动判断论文结论是否可靠；
    4. 自动接受任何论文。
    """

    VALID_ACTIONS = (
        "accept",
        "reject",
        "defer",
    )

    def __init__(
        self,
        repository: LiteratureRepository | None = None,
    ) -> None:
        self.repository = (
            repository
            or LiteratureRepository()
        )

    def review(
        self,
        candidates: list[dict[str, Any]],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        """
        校验并应用人工审查决定。

        decision 格式：

        {
            "accept": ["E1"],
            "reject": ["E2"],
            "defer": ["E3"],
            "note": "人工审查说明"
        }
        """

        if not isinstance(candidates, list):
            raise TypeError(
                "candidates 必须是列表。"
            )

        if not isinstance(decision, dict):
            raise TypeError(
                "decision 必须是字典。"
            )

        papers = self._prepare_candidates(
            candidates
        )

        known_ids = set(papers)

        normalized_decision = {
            action: self._normalize_ids(
                decision.get(action, []),
                action=action,
            )
            for action in self.VALID_ACTIONS
        }

        self._check_conflicts(
            normalized_decision
        )

        selected_ids = set().union(
            *(
                set(normalized_decision[action])
                for action in self.VALID_ACTIONS
            )
        )

        unknown_ids = sorted(
            selected_ids - known_ids
        )

        if unknown_ids:
            raise ValueError(
                "审查决定包含不存在的证据编号："
                + ", ".join(unknown_ids)
            )

        # 没有明确接受或拒绝的论文默认暂缓，
        # 防止遗漏操作被错误解释为接受。
        unclassified_ids = sorted(
            known_ids - selected_ids,
            key=self._evidence_sort_key,
        )

        normalized_decision["defer"].extend(
            unclassified_ids
        )

        normalized_decision["defer"] = (
            self._unique_ids(
                normalized_decision["defer"]
            )
        )

        accepted = self._select_papers(
            papers,
            normalized_decision["accept"],
            review_status="accepted",
        )
        accepted = [
            self._annotate_evidence_use(paper)
            for paper in accepted
        ]

        rejected = self._select_papers(
            papers,
            normalized_decision["reject"],
            review_status="rejected",
        )

        deferred = self._select_papers(
            papers,
            normalized_decision["defer"],
            review_status="deferred",
        )

        assertion_decision = self._review_assertions(
            accepted,
            self._accepted_assertion_decisions(
                papers,
                normalized_decision["accept"],
                decision.get("assertions", {}),
            ),
        )
        accepted = assertion_decision["papers"]

        note = str(
            decision.get("note", "") or ""
        ).strip()

        return {
            "status": "review_completed",
            "decision": {
                "accept": [
                    paper["evidence_id"]
                    for paper in accepted
                ],
                "reject": [
                    paper["evidence_id"]
                    for paper in rejected
                ],
                "defer": [
                    paper["evidence_id"]
                    for paper in deferred
                ],
                "note": note,
            },
            "candidate_count": len(papers),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "deferred_count": len(deferred),
            "unclassified_moved_to_defer": (
                unclassified_ids
            ),
            "accepted": accepted,
            "rejected": rejected,
            "deferred": deferred,
            "assertion_review": assertion_decision["summary"],
            "accepted_assertions": assertion_decision["accepted"],
            "requires_human_review": False,
            "warnings": [
                (
                    "人工接受表示允许本 Agent 使用该论文，"
                    "不代表论文结论已经被科学验证。"
                ),
                *(
                    [
                        "The user accepted this composition as an ideal "
                        "modeling hypothesis for C-stage candidate design."
                    ]
                    if any(
                        paper.get("evidence_use_mode")
                        == "ideal_modeling_hypothesis"
                        for paper in accepted
                    )
                    else []
                ),
            ],
        }

    @staticmethod
    def _accepted_assertion_decisions(
        papers: dict[str, dict[str, Any]],
        accepted_evidence_ids: list[str],
        decision: Any,
    ) -> dict[str, list[str]]:
        """Discard assertion decisions for rejected or deferred papers."""
        decision = decision if isinstance(decision, dict) else {}
        allowed = {
            str(assertion.get("assertion_id", "")).strip()
            for evidence_id in accepted_evidence_ids
            for assertion in papers.get(evidence_id, {}).get("assertions", [])
            if isinstance(assertion, dict) and assertion.get("assertion_id")
        }
        return {
            action: [
                str(value).strip()
                for value in decision.get(action, [])
                if str(value).strip() in allowed
            ]
            for action in LiteratureReviewGate.VALID_ACTIONS
        }

    @staticmethod
    def _annotate_evidence_use(
        paper: dict[str, Any],
    ) -> dict[str, Any]:
        item = dict(paper)
        level = literature_verification_level(item)
        if level == "unverified":
            item.pop("verification_level", None)
            item["evidence_use_mode"] = "ideal_modeling_hypothesis"
            item["evidence_use_label"] = "理想建模假设"
            item["requires_secondary_verification"] = False
            item["requires_human_confirmation"] = False
        else:
            item["evidence_use_mode"] = "reviewed_literature_evidence"
            item["requires_secondary_verification"] = level == "single_source"
        return item

    @staticmethod
    def _review_assertions(
        accepted_papers: list[dict[str, Any]],
        decision: Any,
    ) -> dict[str, Any]:
        decision = decision if isinstance(decision, dict) else {}
        accepted_ids = {
            str(value).strip() for value in decision.get("accept", [])
        }
        rejected_ids = {
            str(value).strip() for value in decision.get("reject", [])
        }
        deferred_ids = {
            str(value).strip() for value in decision.get("defer", [])
        }
        if accepted_ids & rejected_ids or accepted_ids & deferred_ids or rejected_ids & deferred_ids:
            raise ValueError("The same assertion cannot receive multiple review decisions.")
        known = set()
        reviewed_papers = []
        accepted_assertions = []
        counts = {"accepted": 0, "rejected": 0, "deferred": 0}
        for paper in accepted_papers:
            item = dict(paper)
            assertions = []
            for index, assertion in enumerate(paper.get("assertions", []), 1):
                if not isinstance(assertion, dict):
                    continue
                claim = dict(assertion)
                assertion_id = str(
                    claim.get("assertion_id")
                    or f"{paper.get('evidence_id', 'E')}::A{index}"
                )
                known.add(assertion_id)
                if assertion_id in accepted_ids:
                    status = "accepted"
                elif assertion_id in rejected_ids:
                    status = "rejected"
                else:
                    status = "deferred"
                claim["assertion_id"] = assertion_id
                claim["review_status"] = status
                counts[status] += 1
                assertions.append(claim)
                if status == "accepted":
                    accepted_assertions.append({
                        "evidence_id": paper.get("evidence_id", ""),
                        "paper_id": paper.get("paper_id", ""),
                        **claim,
                    })
            item["assertions"] = assertions
            reviewed_papers.append(item)
        unknown = (accepted_ids | rejected_ids | deferred_ids) - known
        if unknown:
            raise ValueError("Unknown assertion IDs: " + ", ".join(sorted(unknown)))
        return {
            "papers": reviewed_papers,
            "accepted": accepted_assertions,
            "summary": {
                "status": "assertion_review_completed",
                "candidate_count": len(known),
                "accepted_count": counts["accepted"],
                "rejected_count": counts["rejected"],
                "deferred_count": counts["deferred"],
                "unclassified_default": "deferred",
            },
        }

    def commit_accepted(
        self,
        review_result: dict[str, Any],
    ) -> dict[str, Any]:
        """
        将人工接受的纯在线论文写入正式数据库。

        以下记录不会写入：
        1. 本地已有记录；
        2. local+online 合并记录；
        3. 被拒绝或暂缓的记录；
        4. sample 开发记录；
        5. 缺少 paper_id 或标题的记录；
        6. 数据库中已有相同 paper_id 或 DOI 的记录。
        """

        if not isinstance(review_result, dict):
            raise TypeError(
                "review_result 必须是字典。"
            )

        if (
            review_result.get("status")
            != "review_completed"
        ):
            raise ValueError(
                "只有 review_completed 结果可以入库。"
            )

        accepted = review_result.get(
            "accepted",
            [],
        )

        if not isinstance(accepted, list):
            raise TypeError(
                "review_result.accepted 必须是列表。"
            )

        database_count_before = (
            self.repository.count()
        )

        stored: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []

        for paper in accepted:
            if not isinstance(paper, dict):
                skipped.append(
                    {
                        "evidence_id": "",
                        "paper_id": "",
                        "reason": (
                            "接受列表中存在非字典记录"
                        ),
                    }
                )
                continue

            evidence_id = str(
                paper.get("evidence_id", "")
                or ""
            ).strip()

            paper_id = str(
                paper.get("paper_id", "")
                or ""
            ).strip()

            title = str(
                paper.get("title", "")
                or ""
            ).strip()

            origin = str(
                paper.get(
                    "retrieval_origin",
                    "",
                )
                or ""
            ).strip().lower()

            source = str(
                paper.get("source", "")
                or ""
            ).strip().lower()

            if origin != "online":
                skipped.append(
                    {
                        "evidence_id": evidence_id,
                        "paper_id": paper_id,
                        "reason": (
                            "不是纯在线候选，"
                            "本地或合并记录无需重复入库"
                        ),
                    }
                )
                continue

            if (
                paper_id.lower().startswith(
                    "sample:"
                )
                or source == "sample"
            ):
                skipped.append(
                    {
                        "evidence_id": evidence_id,
                        "paper_id": paper_id,
                        "reason": (
                            "sample 开发记录禁止写入"
                            "正式科研文献库"
                        ),
                    }
                )
                continue

            if not paper_id:
                skipped.append(
                    {
                        "evidence_id": evidence_id,
                        "paper_id": "",
                        "reason": "缺少 paper_id",
                    }
                )
                continue

            if not title:
                skipped.append(
                    {
                        "evidence_id": evidence_id,
                        "paper_id": paper_id,
                        "reason": "缺少论文标题",
                    }
                )
                continue

            duplicate_reason = (
                self._duplicate_reason(paper)
            )

            if duplicate_reason:
                skipped.append(
                    {
                        "evidence_id": evidence_id,
                        "paper_id": paper_id,
                        "reason": duplicate_reason,
                    }
                )
                continue

            try:
                record = PaperRecord.from_dict(
                    paper
                )

                self.repository.upsert(record)

                stored.append(
                    {
                        "evidence_id": evidence_id,
                        "paper_id": paper_id,
                        "title": title,
                    }
                )

            except Exception as error:
                errors.append(
                    {
                        "evidence_id": evidence_id,
                        "paper_id": paper_id,
                        "error_type": (
                            type(error).__name__
                        ),
                        "message": str(error),
                    }
                )

        database_count_after = (
            self.repository.count()
        )

        return {
            "status": (
                "commit_completed"
                if not errors
                else "commit_completed_with_errors"
            ),
            "database_count_before": (
                database_count_before
            ),
            "database_count_after": (
                database_count_after
            ),
            "stored_count": len(stored),
            "skipped_count": len(skipped),
            "error_count": len(errors),
            "stored": stored,
            "skipped": skipped,
            "errors": errors,
        }

    @staticmethod
    def _prepare_candidates(
        candidates: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        papers: dict[str, dict[str, Any]] = {}

        for index, candidate in enumerate(
            candidates,
            start=1,
        ):
            if not isinstance(candidate, dict):
                raise TypeError(
                    "每个候选文献都必须是字典。"
                )

            paper = dict(candidate)

            evidence_id = str(
                paper.get("evidence_id", "")
                or f"E{index}"
            ).strip().upper()

            if not evidence_id:
                raise ValueError(
                    "证据编号不能为空。"
                )

            if evidence_id in papers:
                raise ValueError(
                    f"证据编号重复：{evidence_id}"
                )

            paper["evidence_id"] = evidence_id
            papers[evidence_id] = paper

        return papers

    @staticmethod
    def _normalize_ids(
        values: Any,
        action: str,
    ) -> list[str]:
        if values is None:
            return []

        if isinstance(values, str):
            values = [
                part
                for part in values.replace(
                    "，",
                    ",",
                ).split(",")
                if part.strip()
            ]

        if not isinstance(values, list):
            raise TypeError(
                f"decision.{action} 必须是列表"
                "或逗号分隔的字符串。"
            )

        normalized: list[str] = []

        for value in values:
            evidence_id = str(
                value or ""
            ).strip().upper()

            if (
                evidence_id
                and evidence_id not in normalized
            ):
                normalized.append(evidence_id)

        return normalized

    @staticmethod
    def _check_conflicts(
        decision: dict[str, list[str]],
    ) -> None:
        owners: dict[str, list[str]] = {}

        for action, evidence_ids in (
            decision.items()
        ):
            for evidence_id in evidence_ids:
                owners.setdefault(
                    evidence_id,
                    [],
                ).append(action)

        conflicts = {
            evidence_id: actions
            for evidence_id, actions
            in owners.items()
            if len(actions) > 1
        }

        if conflicts:
            descriptions = [
                (
                    f"{evidence_id} 同时出现在 "
                    + "/".join(actions)
                )
                for evidence_id, actions
                in sorted(conflicts.items())
            ]

            raise ValueError(
                "同一证据不能被重复分类："
                + "；".join(descriptions)
            )

    @staticmethod
    def _select_papers(
        papers: dict[str, dict[str, Any]],
        evidence_ids: list[str],
        review_status: str,
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []

        for evidence_id in evidence_ids:
            paper = dict(papers[evidence_id])
            paper["review_status"] = (
                review_status
            )
            selected.append(paper)

        return selected

    @staticmethod
    def _unique_ids(
        values: list[str],
    ) -> list[str]:
        result: list[str] = []

        for value in values:
            if value not in result:
                result.append(value)

        return result

    @staticmethod
    def _evidence_sort_key(
        evidence_id: str,
    ) -> tuple[int, str]:
        suffix = evidence_id[1:]

        if (
            evidence_id.startswith("E")
            and suffix.isdigit()
        ):
            return int(suffix), evidence_id

        return 10**9, evidence_id

    def _duplicate_reason(
        self,
        paper: dict[str, Any],
    ) -> str:
        paper_id = str(
            paper.get("paper_id", "")
            or ""
        ).strip()

        doi = self._normalize_doi(
            paper.get("doi", "")
        )

        with self.repository.connect() as connection:
            if paper_id:
                existing = connection.execute(
                    """
                    SELECT paper_id
                    FROM papers
                    WHERE lower(paper_id) = lower(?)
                    LIMIT 1
                    """,
                    (paper_id,),
                ).fetchone()

                if existing is not None:
                    return (
                        "数据库已存在相同 paper_id"
                    )

            if doi:
                rows = connection.execute(
                    """
                    SELECT paper_id, doi
                    FROM papers
                    WHERE doi IS NOT NULL
                      AND trim(doi) != ''
                    """
                ).fetchall()

                for row in rows:
                    existing_doi = (
                        self._normalize_doi(
                            row["doi"]
                        )
                    )

                    if existing_doi == doi:
                        return (
                            "数据库已存在相同 DOI，"
                            f"paper_id={row['paper_id']}"
                        )

        return ""

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

        return doi.strip().rstrip(".")
