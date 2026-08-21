from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any

from langgraph.types import Command

from app.graph.workflow import graph


def _legacy_c8_not_executed_reason(
    result: dict[str, Any],
) -> str:
    """Explain why C8 has no result without confusing pending DFT with failure."""

    formation = result.get("formation_energy_evaluation", {})
    stability = result.get("stability_screening", {})
    dft_queue = result.get("dft_formation_energy_queue", [])
    waiting_count = int(
        formation.get("waiting_for_dft_count", 0) or 0
    ) if isinstance(formation, dict) else 0
    if (
        (isinstance(dft_queue, list) and bool(dft_queue))
        or waiting_count > 0
        or (
            isinstance(formation, dict)
            and formation.get("status") == "formation_energy_waiting_for_dft"
        )
    ):
        return (
            "C6 正在等待 Bulk DFT 形成能计算、解析和回填；"
            "C7 尚未执行，因此 C8 暂未执行。"
        )

    stability_status = str(
        stability.get("status", "") or ""
    ) if isinstance(stability, dict) else ""
    if (
        stability_status.startswith("stability_screening_completed")
        and int(stability.get("passed_count", 0) or 0) == 0
    ):
        return "没有结构通过 C7 稳定性筛选，C8 未执行。"

    return "C7 尚未产生可进入 slab 生成的结构，C8 未执行。"


def c8_not_executed_reason(
    result: dict[str, Any],
) -> str:
    """Explain the current C8 boundary using the post-C7 review state."""

    formation = result.get("formation_energy_evaluation", {})
    stability = result.get("stability_screening", {})
    dft_queue = result.get("dft_formation_energy_queue", [])
    waiting_count = int(
        formation.get("waiting_for_dft_count", 0) or 0
    ) if isinstance(formation, dict) else 0
    if (
        (isinstance(dft_queue, list) and bool(dft_queue))
        or waiting_count > 0
        or (
            isinstance(formation, dict)
            and formation.get("status") == "formation_energy_waiting_for_dft"
        )
    ):
        return (
            "C6 正在等待 Bulk DFT 形成能计算、解析和回填；"
            "C7 尚未执行，因此 C8 暂未执行。"
        )

    passed_count = int(
        stability.get("passed_count", 0) or 0
    ) if isinstance(stability, dict) else 0
    stability_status = str(
        stability.get("status", "") or ""
    ) if isinstance(stability, dict) else ""
    if stability_status.startswith("stability_screening_completed") and not passed_count:
        return "没有结构通过 C7 稳定性筛选，C8 未执行。"

    review = result.get("c7_dft_upgrade_review", {})
    if passed_count > 0 and isinstance(review, dict) and review:
        if int(review.get("selected_count", 0) or 0) == 0:
            return "C7 已有通过结构，但人工 DFT 升级门未批准任何结构进入 C8。"
    if passed_count > 0 and result.get("c_stage_execution_mode") == "stability_screening":
        return "C7 已有通过结构，正在等待人工选择哪些结构进入 C8 和后续 DFT。"
    return "C7 尚未产生可进入 slab 生成的结构，C8 未执行。"


def print_section(
    title: str,
    value: Any,
) -> None:
    """用统一格式输出一个结果区域。"""

    not_executed_reasons = {
        "Agent 能力边界": "明确五元组成已从 A 阶段直接进入 C，普通能力门未执行。",
        "入口路由": "明确五元组成已从 A 阶段直接进入 C，B 阶段入口路由未执行。",
        "任务规划": "明确五元组成已从 A 阶段直接进入 C，B 阶段规划未执行。",
        "联网检索决策": "用户明确要求不检索文献，B 阶段未执行。",
        "C8 FCC(111)切面结果": "没有结构通过 C7 稳定性筛选，C8 未执行。",
        "C9 slab 自动质量检查": "C8 未生成 slab，C9 自动检查未执行。",
        "C9 slab 人工确认结果": "C8 未生成 slab，C9 人工确认未执行。",
        "C6D bulk DFT 输入文件": "当前流程没有结构进入 bulk DFT 队列。",
        "C11.2 本地五文件预检查": "当前流程没有生成待提交的 DFT 作业。",
        "C11.3 cluster read-only preflight": "当前流程没有待提交的 DFT 作业。",
        "C11.4.1 remote execution plan": "当前流程没有待提交的 DFT 作业。",
        "C11.4.2 remote upload result": "当前流程没有待上传的 DFT 作业。",
        "C11.4.3 remote Slurm submission": "当前流程没有待提交的 DFT 作业。",
        "C11.5.1 persisted Slurm jobs": "当前流程没有已提交的 Slurm 作业。",
        "C10 revision history": "C10 未执行，因此没有修订历史。",
        "C10 VASP 计算文件": "没有通过 C9 人工确认的 slab，C10 未执行。",
    }
    reason = not_executed_reasons.get(title)
    if reason and (
        not isinstance(value, dict)
        or not value
        or value.get("status") is None
    ):
        value = {
            "status": "not_executed",
            "reason": reason,
        }

    print()
    print("=" * 70)
    print(title)
    print("=" * 70)

    if isinstance(value, str):
        print(value or "无")
        return

    print(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
    )


def collect_review_decision(
    review_request: dict[str, Any],
) -> dict[str, Any]:
    """逐篇展示文献信息并收集人工审查决定。"""

    candidates = review_request.get(
        "candidates",
        [],
    )

    if not isinstance(candidates, list):
        candidates = []

    accept: list[str] = []
    reject: list[str] = []
    defer: list[str] = []
    assertion_accept: list[str] = []
    assertion_reject: list[str] = []
    assertion_defer: list[str] = []

    print()
    print("=" * 70)
    print("文献人工审查")
    print("=" * 70)
    print(
        review_request.get(
            "message",
            "请审查候选论文。",
        )
    )
    print(
        f"本轮共有 {len(candidates)} "
        "篇候选论文。"
    )

    for index, paper in enumerate(
        candidates,
        start=1,
    ):
        evidence_id = str(
            paper.get(
                "evidence_id",
                f"E{index}",
            )
        ).strip().upper()

        print()
        print("-" * 70)
        print(
            f"[{evidence_id}] "
            f"{paper.get('title') or '未提供标题'}"
        )
        print("-" * 70)

        print(
            "年份：",
            paper.get("year") or "未提供",
        )

        print(
            "期刊：",
            paper.get("journal")
            or "未提供",
        )

        print(
            "DOI：",
            paper.get("doi")
            or "未提供",
        )

        print(
            "URL：",
            paper.get("url")
            or "未提供",
        )

        print(
            "来源：",
            paper.get("retrieval_origin")
            or paper.get("source")
            or "未知",
        )

        print(
            "证据质量：",
            (
                f"{paper.get('quality_level', 'D')} "
                f"({paper.get('quality_score', 0)}/100)"
            ),
        )

        if paper.get("cross_verified"):
            print("文献来源状态：Crossref + Semantic Scholar互证")
        else:
            print("证据用途：人工接受后作为理想建模假设进入C阶段")
        verification_level = paper.get("verification_level", "unverified")
        verification_labels = {
            "dual_source": "双源核验",
            "single_source": "单源核验（允许人工批准，待二次互证）",
            "unverified": "理想建模假设",
        }
        print(
            "文献核验等级：",
            verification_labels.get(verification_level, verification_level),
        )
        print(
            "目标反应匹配：",
            "通过" if paper.get("reaction_direct") else "未通过",
        )

        dimension_labels = (
            ("metadata_quality", "元数据完整度"),
            ("task_relevance", "任务相关性"),
            ("claim_evidence_quality", "可引用主张证据"),
            ("journal_impact", "期刊影响因子"),
        )
        print("评分维度：")
        for field, label in dimension_labels:
            dimension = paper.get(field, {})
            if not isinstance(dimension, dict):
                dimension = {}
            print(
                f"  - {label}: {dimension.get('score', 0)}"
                f"/{dimension.get('max_score', 0)}"
            )
            components = dimension.get("components", {})
            if isinstance(components, dict) and components:
                print(
                    "    子项：",
                    json.dumps(components, ensure_ascii=False),
                )

        print(
            "明确金属组成：",
            paper.get("composition_elements", []) or "未检出",
        )
        print(
            "四/五元高熵组成资格：",
            "满足" if paper.get("hea_composition_eligible") else "不满足",
        )
        print(
            "常用 HEA 过渡金属：",
            paper.get("common_hea_transition_metals", []) or "未检出",
        )

        journal_impact = paper.get("journal_impact", {})
        if isinstance(journal_impact, dict):
            print("影响因子记录：", {
                "value": journal_impact.get("impact_factor"),
                "year": journal_impact.get("metric_year"),
                "source": journal_impact.get("source", ""),
                "status": journal_impact.get("status", "unavailable"),
            })

        claim_quality = paper.get("claim_evidence_quality", {})
        if isinstance(claim_quality, dict):
            print("组成证据原文：")
            composition_claims = claim_quality.get("composition_claims", [])
            if composition_claims:
                for claim in composition_claims:
                    print("  -", claim)
            else:
                print("  - 未检出")

        quality_issues = paper.get(
            "quality_issues",
            [],
        )

        if quality_issues:
            print(
                "质量提示：",
                "；".join(
                    str(item)
                    for item in quality_issues
                ),
            )
        else:
            print("质量提示：无")

        version_info = paper.get(
            "version_info",
            {},
        )

        if isinstance(version_info, dict):
            has_preprint = bool(
                version_info.get(
                    "has_preprint_version"
                )
            )

            has_formal = bool(
                version_info.get(
                    "has_formal_version"
                )
            )

            if has_preprint and has_formal:
                print(
                    "版本提示：同时发现预印本和"
                    "正式期刊版本，请重点核对 DOI。"
                )
            elif has_preprint:
                print(
                    "版本提示：当前记录可能是预印本。"
                )
            elif has_formal:
                print(
                    "版本提示：当前主记录为正式期刊版本。"
                )
            else:
                print(
                    "版本提示：尚未确认正式发表状态。"
                )

        print()
        print("摘要原文：")
        print(
            paper.get("abstract")
            or "未提供摘要"
        )

        while True:
            print()
            action = input(
                "请选择："
                "[a] 接受  "
                "[r] 拒绝  "
                "[d] 暂缓（默认）\n> "
            ).strip().lower()

            if action in {"", "d", "defer"}:
                defer.append(evidence_id)
                print(
                    f"{evidence_id} 已标记为暂缓。"
                )
                break

            if action in {"a", "accept"}:
                accept.append(evidence_id)
                print(
                    f"{evidence_id} 已标记为接受。"
                )
                assertions = paper.get("assertions", [])
                if isinstance(assertions, list) and assertions:
                    print("\n断言级审查（未分类断言默认暂缓）：")
                    for claim_index, assertion in enumerate(assertions, 1):
                        if not isinstance(assertion, dict):
                            continue
                        assertion_id = str(
                            assertion.get("assertion_id")
                            or f"{evidence_id}::A{claim_index}"
                        )
                        print("-" * 50)
                        print(f"[{assertion_id}] 类型：{assertion.get('kind', '')}")
                        print("值：", json.dumps(
                            assertion.get("value"), ensure_ascii=False
                        ))
                        print(
                            "证据级别/置信度：",
                            assertion.get("evidence_level", "missing"),
                            "/",
                            assertion.get("confidence", "low"),
                        )
                        for evidence in assertion.get("evidence", []):
                            if isinstance(evidence, dict):
                                print("原文：", evidence.get("quote", ""))
                        claim_action = input(
                            "[a] 接受断言  [r] 拒绝断言  [d] 暂缓（默认）\n> "
                        ).strip().lower()
                        if claim_action in {"a", "accept"}:
                            assertion_accept.append(assertion_id)
                        elif claim_action in {"r", "reject"}:
                            assertion_reject.append(assertion_id)
                        else:
                            assertion_defer.append(assertion_id)
                break

            if action in {"r", "reject"}:
                reject.append(evidence_id)
                print(
                    f"{evidence_id} 已标记为拒绝。"
                )
                break

            print(
                "输入无效，请输入 a、r 或 d。"
            )

    print()
    note = input(
        "请输入本轮人工审查备注"
        "（可以直接回车跳过）：\n> "
    ).strip()

    decision = {
        "accept": accept,
        "reject": reject,
        "defer": defer,
        "assertions": {
            "accept": assertion_accept,
            "reject": assertion_reject,
            "defer": assertion_defer,
        },
        "note": note,
    }

    print_section(
        "准备提交的人工审查决定",
        decision,
    )

    return decision


def collect_candidate_review_decision(
    review_request: dict[str, Any],
) -> dict[str, Any]:
    """展示排名候选并收集人工选择。"""

    candidates = review_request.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []

    max_selected = int(review_request.get("max_selected", 3))
    selected: list[str] = []
    rejected: list[str] = []
    deferred: list[str] = []

    print()
    print("=" * 70)
    fixed_composition = bool(candidates) and all(
        candidate.get("candidate_kind")
        == "fixed_composition_fcc_arrangement"
        for candidate in candidates
    )
    entity_label = "固定组成 FCC 原子排布" if fixed_composition else "候选材料"
    print(f"{entity_label}人工确认")
    print("=" * 70)
    print(
        review_request.get(
            "message",
            f"请选择进入后续 FCC 建模的{entity_label}。",
        )
    )
    print(
        f"完整候选池共 "
        f"{review_request.get('total_candidate_count', len(candidates))} "
        f"个，本轮显示前 {len(candidates)} 个。"
    )
    print(f"本轮最多选择 {max_selected} 个{entity_label}。")

    warning = review_request.get("scientific_warning", "")
    if warning:
        print()
        print("科学边界提示：")
        print(warning)

    for index, candidate in enumerate(candidates, start=1):
        candidate_id = str(
            candidate.get("candidate_id", f"C{index}")
        ).strip()

        print()
        print("-" * 70)
        rank_label = "排布" if fixed_composition else "排名"
        print(f"[{rank_label} {candidate.get('rank', index)}] {candidate_id}")
        print("-" * 70)
        print("元素：", ", ".join(candidate.get("elements", [])))
        print("32原子组成：", candidate.get("composition", {}))
        print("综合评分：", candidate.get("total_score", 0.0))

        scores = candidate.get("scores", {})
        if isinstance(scores, dict):
            print("六维子评分：", json.dumps(scores, ensure_ascii=False))

        evidence = candidate.get("best_literature_evidence")
        if isinstance(evidence, dict) and evidence:
            print(
                "最佳文献证据：",
                evidence.get("evidence_id", ""),
                evidence.get("title", ""),
            )
            print("DOI：", evidence.get("doi", "") or "未提供")
        else:
            print("最佳文献证据：无直接元素组合证据")

        risks = candidate.get("highest_risk_elements", [])
        print(
            "需关注的元素风险：",
            ", ".join(risks) if risks else "未标记",
        )
        process_risks = candidate.get("active_process_risks", {})
        print(
            "合成工艺风险：",
            process_risks if process_risks else "未标记",
        )

        while True:
            action = input(
                "\n请选择："
                "[s] 选择进入建模  "
                "[r] 拒绝  "
                "[d] 暂缓（默认）\n> "
            ).strip().lower()

            if action in {"", "d", "defer"}:
                deferred.append(candidate_id)
                print(f"{candidate_id} 已标记为暂缓。")
                break

            if action in {"s", "select"}:
                if len(selected) >= max_selected:
                    print(
                        f"最多只能选择 {max_selected} 个候选，"
                        "请改为拒绝或暂缓。"
                    )
                    continue
                selected.append(candidate_id)
                print(f"{candidate_id} 已选择进入后续建模。")
                break

            if action in {"r", "reject"}:
                rejected.append(candidate_id)
                print(f"{candidate_id} 已标记为拒绝。")
                break

            print("输入无效，请输入 s、r、d，或直接回车表示暂缓。")

    note = input(
        "\n请输入本轮候选选择备注（可以直接回车跳过）：\n> "
    ).strip()
    decision = {
        "select": selected,
        "reject": rejected,
        "defer": deferred,
        "note": note,
    }
    print_section("准备提交的候选选择决定", decision)
    return decision


def collect_c_stage_execution_decision(
    review_request: dict[str, Any],
) -> dict[str, Any]:
    """Explain C-stage boundaries and collect explicit user consent."""

    print()
    print("=" * 70)
    print("C 阶段后续理论工作确认")
    print("=" * 70)
    print(review_request.get("message", ""))
    print("已选候选：", ", ".join(
        review_request.get("selected_candidate_ids", [])
    ))
    print("[0] 只保留候选组合并停止")
    print("[1] 仅进行 FCC bulk 结构建模")
    print("    FCC 是金属高熵合金常用的起始建模结构，但不是相结构证明。")
    print("[2] FCC + 形成能预测 + delta/Omega 稳定性预筛（推荐）")
    print("    低成本理论指标可在昂贵 DFT 前筛除较弱候选。")
    print("[3] 继续完整 DFT 验证流程")
    print("    DFT 理论可信度更高，但成本较高，通常需要超算。")
    print("    上传和 sbatch 提交仍需通过已有的独立人工确认门。")

    modes = {
        "0": "candidate_only",
        "1": "fcc_only",
        "2": "stability_screening",
        "3": "dft_validation",
    }
    while True:
        choice = input("\n请选择 0/1/2/3（回车默认为 0）：\n> ").strip()
        if choice == "":
            choice = "0"
        if choice in modes:
            break
        print("输入无效，请输入 0、1、2 或 3。")

    note = input("可选备注（回车跳过）：\n> ").strip()
    decision = {"mode": modes[choice], "note": note}
    print_section("C 阶段执行范围决定", decision)
    return decision


def collect_c7_dft_upgrade_decision(
    review_request: dict[str, Any],
) -> dict[str, Any]:
    """Select a subset of C7-passed structures for C8 and later DFT work."""

    structures = review_request.get("structures", [])
    if not isinstance(structures, list):
        structures = []
    selected: list[str] = []
    rejected: list[str] = []
    deferred: list[str] = []

    print()
    print("=" * 70)
    print("C7 通过结构的 DFT 升级选择")
    print("=" * 70)
    print(review_request.get("message", ""))
    print(review_request.get("safety_notice", ""))

    for structure in structures:
        structure_id = str(structure.get("structure_id", "")).strip()
        print()
        print("-" * 70)
        print(f"结构 ID：{structure_id}")
        print("候选 ID：", structure.get("candidate_id", ""))
        print("组成：", structure.get("composition", {}))
        print(
            "形成能：",
            structure.get("formation_energy_ev_per_atom"),
            "eV/atom",
        )
        print("delta：", structure.get("delta_percent"), "%")
        print("Omega：", structure.get("omega"))
        print("CIF：", structure.get("cif_path", ""))
        print("POSCAR：", structure.get("poscar_path", ""))

        while True:
            action = input(
                "\n请选择：[s] 进入 C8/DFT  "
                "[r] 拒绝  [d] 暂缓（默认）\n> "
            ).strip().lower()
            if action in {"s", "select", "a", "approve"}:
                selected.append(structure_id)
                break
            if action in {"r", "reject"}:
                rejected.append(structure_id)
                break
            if action in {"", "d", "defer"}:
                deferred.append(structure_id)
                break
            print("输入无效，请输入 s、r、d，或直接回车表示暂缓。")

    note = input("\n请输入 C7 后 DFT 选择备注（可直接回车）：\n> ").strip()
    decision = {
        "select": selected,
        "reject": rejected,
        "defer": deferred,
        "note": note,
    }
    print_section("C7 后 DFT 升级决定", decision)
    return decision


def collect_slab_review_decision(
    review_request: dict[str, Any],
) -> dict[str, Any]:
    """Display C9 reports and collect slab decisions."""

    slabs = review_request.get("slabs", [])
    if not isinstance(slabs, list):
        slabs = []

    approve: list[str] = []
    reject: list[str] = []
    defer: list[str] = []

    print()
    print("=" * 70)
    print("C9 slab 人工确认")
    print("=" * 70)
    print(review_request.get("message", ""))

    for slab in slabs:
        slab_id = str(
            slab.get("slab_id", "")
        ).strip()

        print()
        print("-" * 70)
        print(f"[{slab_id}]")
        print("-" * 70)
        print("原子数：", slab.get("atom_count"))
        print("元素数：", slab.get("element_count"))
        print(
            "最小原子间距：",
            slab.get("minimum_distance_angstrom"),
            "Å",
        )
        print(
            "真空层：",
            slab.get("measured_vacuum_angstrom"),
            "Å",
        )
        print(
            "固定/可移动原子：",
            slab.get("fixed_atom_count"),
            "/",
            slab.get("movable_atom_count"),
        )
        print("CIF：", slab.get("cif_path"))
        print("POSCAR：", slab.get("poscar_path"))

        while True:
            action = input(
                "\n请选择："
                "[a] 批准进入 DFT  "
                "[r] 拒绝  "
                "[d] 暂缓（默认）\n> "
            ).strip().lower()

            if action in {"a", "approve"}:
                approve.append(slab_id)
                break
            if action in {"r", "reject"}:
                reject.append(slab_id)
                break
            if action in {"", "d", "defer"}:
                defer.append(slab_id)
                break

            print("输入无效，请输入 a、r 或 d。")

    note = input(
        "\n请输入 slab 审查备注"
        "（可直接回车跳过）：\n> "
    ).strip()

    return {
        "approve": approve,
        "reject": reject,
        "defer": defer,
        "note": note,
    }


def collect_adsorption_structure_review(
    request: dict[str, Any],
) -> dict[str, Any]:
    """Collect C12.4 adsorption decisions."""

    approve: list[str] = []
    reject: list[str] = []
    defer: list[str] = []

    print_section(
        "C12.4 adsorption structure review",
        {
            "message": request.get("message"),
            "maximum_approved": request.get(
                "maximum_approved"
            ),
        },
    )

    for structure in request.get(
        "structures",
        [],
    ):
        print_section(
            str(
                structure.get(
                    "adsorption_structure_id"
                )
            ),
            structure,
        )

        action = input(
            "[a] approve  [r] reject  "
            "[d] defer\n> "
        ).strip().lower()

        identifier = str(
            structure[
                "adsorption_structure_id"
            ]
        )

        if action in {"a", "approve"}:
            approve.append(identifier)
        elif action in {"r", "reject"}:
            reject.append(identifier)
        else:
            defer.append(identifier)

    note = input(
        "Review note, or press Enter:\n> "
    ).strip()

    return {
        "approve": approve,
        "reject": reject,
        "defer": defer,
        "note": note,
    }


def collect_adsorption_intermediate_review(
    request: dict[str, Any],
) -> dict[str, Any]:
    """Collect exactly one C12.1 adsorption intermediate."""

    candidates = request.get("candidate_adsorbates", [])
    print_section(
        "C12.1 single-intermediate selection",
        {
            "message": request.get("message"),
            "candidate_adsorbates": candidates,
            "reference_energy_definitions": request.get(
                "reference_energy_definitions", {}
            ),
        },
    )
    while True:
        for index, adsorbate in enumerate(candidates, 1):
            print(f"[{index}] {adsorbate}")
        answer = input("Select one intermediate by number or name:\n> ").strip()
        selected = ""
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            selected = str(candidates[int(answer) - 1])
        elif answer in candidates:
            selected = answer
        if selected:
            note = input("Selection note, or press Enter:\n> ").strip()
            return {"selected_adsorbate": selected, "note": note}
        print("Please select exactly one listed intermediate.")


def collect_dft_input_review_decision(
    request: dict[str, Any],
) -> dict[str, Any]:
    """Display C10 previews and collect five-file confirmation."""

    stage_label = str(request.get("stage_label", "C10"))
    bundles = request.get("bundles", [])
    if not isinstance(bundles, list):
        bundles = []

    approve: list[str] = []
    reject: list[str] = []
    defer: list[str] = []
    confirmations: dict[str, dict[str, bool]] = {}
    revision_requests: dict[str, str] = {}

    validation = request.get("revision_validation", {})
    if validation:
        print_section(
            f"{stage_label} revision validation",
            validation,
        )

    revision_count = int(request.get("revision_count", 0))
    print(f"{stage_label} revision count: {revision_count}/5")

    for bundle in bundles:
        bundle_id = str(bundle.get("bundle_id", "")).strip()
        preview = bundle.get("preview", {})

        print_section(
            f"{bundle_id} / POSCAR",
            preview.get("POSCAR", ""),
        )
        print_section(
            f"{bundle_id} / INCAR",
            preview.get("INCAR", ""),
        )
        print_section(
            f"{bundle_id} / KPOINTS",
            preview.get("KPOINTS", ""),
        )
        print_section(
            f"{bundle_id} / POTCAR 拼接方案",
            preview.get("POTCAR", []),
        )

        slurm = preview.get("vasp.slurm", {})
        print_section(
            f"{bundle_id} / vasp.slurm 配置",
            {
                key: value
                for key, value in slurm.items()
                if key != "full_text"
            },
        )

        while True:
            action = input(
                "Choose action: [a] approve after five checks, "
                "[m] modify by natural language, [r] reject, "
                "[d] defer\n> "
            ).strip().lower()
            if action in {"a", "approve", "m", "modify", "r", "reject", "d", "defer", ""}:
                break
            print("Invalid action. Enter a, m, r, or d.")

        if action in {"m", "modify"}:
            if revision_count >= 5:
                print(
                    f"Maximum {stage_label} revision count reached; "
                    "this bundle is deferred."
                )
                defer.append(bundle_id)
            else:
                revision_request = input(
                    "Enter the natural-language revision request. "
                    "POSCAR and atomic coordinates are immutable.\n> "
                ).strip()
                if revision_request:
                    revision_requests[bundle_id] = revision_request
                else:
                    defer.append(bundle_id)
            confirmations[bundle_id] = {}
            continue

        if action in {"r", "reject"}:
            reject.append(bundle_id)
            confirmations[bundle_id] = {}
            continue

        if action in {"", "d", "defer"}:
            defer.append(bundle_id)
            confirmations[bundle_id] = {}
            continue

        file_confirmations: dict[str, bool] = {}

        for name in (
            "POSCAR",
            "INCAR",
            "KPOINTS",
            "POTCAR",
            "vasp.slurm",
        ):
            answer = input(
                f"确认 {name}？[y/N]\n> "
            ).strip().lower()

            file_confirmations[name] = (
                answer in {"y", "yes"}
            )

        confirmations[bundle_id] = file_confirmations

        if all(file_confirmations.values()):
            approve.append(bundle_id)
        else:
            defer.append(bundle_id)

    note = input(
        f"请输入 {stage_label} 审查备注"
        "（可直接回车）：\n> "
    ).strip()

    return {
        "action": "revise" if revision_requests else "finalize",
        "approve": approve,
        "reject": reject,
        "defer": defer,
        "file_confirmations": confirmations,
        "revision_requests": revision_requests,
        "note": note,
    }


def collect_remote_upload_review(
    request: dict[str, Any],
) -> dict[str, Any]:
    """Review C11.4.2 remote upload plan."""

    print_section(
        "C11.4.2 remote upload review",
        {
            "task_id": request.get("task_id"),
            "plan_digest": request.get(
                "plan_digest"
            ),
            "remote_batch_directory": request.get(
                "remote_batch_directory"
            ),
            "jobs": [{
                "job_id": job.get("job_id"),
                "remote_job_directory": job.get(
                    "remote_job_directory"
                ),
                "files": [{
                    "name": item.get("name"),
                    "size_bytes": item.get(
                        "size_bytes"
                    ),
                    "sha256": item.get("sha256"),
                } for item in job.get(
                    "files",
                    [],
                )],
            } for job in request.get("jobs", [])],
        },
    )

    approved_job_ids = []

    for job in request.get("jobs", []):
        job_id = str(
            job.get("job_id", "")
        )

        answer = input(
            f"Allow upload of five files for {job_id}? "
            "[y/N]\n> "
        ).strip().lower()

        if answer in {"y", "yes"}:
            approved_job_ids.append(job_id)

    if not approved_job_ids:
        return {
            "action": "defer",
            "approved_job_ids": [],
            "plan_digest": request.get(
                "plan_digest",
                "",
            ),
            "confirmation_text": "",
            "note": "No remote upload was approved.",
        }

    expected = str(
        request.get("confirmation_phrase", "")
    )

    confirmation = input(
        "Remote writing will create directories and "
        "upload files.\n"
        f"Enter the confirmation phrase: {expected}\n> "
    ).strip()

    if confirmation != expected:
        print(
            "Confirmation phrase mismatch; upload deferred."
        )
        return {
            "action": "defer",
            "approved_job_ids": [],
            "plan_digest": request.get(
                "plan_digest",
                "",
            ),
            "confirmation_text": confirmation,
            "note": "Confirmation phrase mismatch.",
        }

    note = input(
        "Enter an upload review note, or press Enter:\n> "
    ).strip()

    return {
        "action": "approve_upload",
        "approved_job_ids": approved_job_ids,
        "plan_digest": request.get(
            "plan_digest",
            "",
        ),
        "confirmation_text": confirmation,
        "note": note,
    }


def collect_remote_submission_review(
    request: dict[str, Any],
) -> dict[str, Any]:
    """Review C11.4.3 Slurm submission."""

    print_section(
        "C11.4.3 remote submission review",
        {
            "task_id": request.get("task_id"),
            "plan_digest": request.get(
                "plan_digest"
            ),
            "jobs": request.get("jobs", []),
            "warning": (
                "Approval will execute sbatch and "
                "consume cluster resources."
            ),
        },
    )

    approved_job_ids = []

    for job in request.get("jobs", []):
        job_id = str(
            job.get("job_id", "")
        )

        answer = input(
            f"Submit {job_id} with vasp.slurm? "
            "[y/N]\n> "
        ).strip().lower()

        if answer in {"y", "yes"}:
            approved_job_ids.append(job_id)

    if not approved_job_ids:
        return {
            "action": "defer",
            "approved_job_ids": [],
            "plan_digest": request.get(
                "plan_digest",
                "",
            ),
            "confirmation_text": "",
            "note": "No Slurm submission was approved.",
        }

    expected = str(
        request.get("confirmation_phrase", "")
    )

    confirmation = input(
        "This action will submit real Slurm jobs.\n"
        f"Enter the confirmation phrase: {expected}\n> "
    ).strip()

    if confirmation != expected:
        print(
            "Confirmation phrase mismatch; "
            "submission deferred."
        )
        return {
            "action": "defer",
            "approved_job_ids": [],
            "plan_digest": request.get(
                "plan_digest",
                "",
            ),
            "confirmation_text": confirmation,
            "note": "Confirmation phrase mismatch.",
        }

    note = input(
        "Enter a submission note, or press Enter:\n> "
    ).strip()

    return {
        "action": "approve_submission",
        "approved_job_ids": approved_job_ids,
        "plan_digest": request.get(
            "plan_digest",
            "",
        ),
        "confirmation_text": confirmation,
        "note": note,
    }


def collect_dft_execution_options(
    request: dict[str, Any],
) -> dict[str, Any]:
    """Collect the C11.1 relax/static/defer choice."""

    print_section(
        "C11.1 DFT 计算精度选择",
        {
            "job_source": request.get("job_source"),
            "job_count": request.get("job_count", 0),
            "jobs": request.get("jobs", []),
            "choices": request.get("choices", []),
        },
    )

    while True:
        answer = input(
            "请选择：[1] 仅弛豫 "
            "[2] 弛豫+静态单点 "
            "[3] 暂不提交\n> "
        ).strip().lower()

        mapping = {
            "1": "relax_only",
            "relax": "relax_only",
            "2": "relax_then_static",
            "static": "relax_then_static",
            "3": "defer",
            "defer": "defer",
        }

        if answer in mapping:
            return {"mode": mapping[answer]}

        print("输入无效，请输入 1、2 或 3。")


def collect_adsorption_dft_execution(
    request: dict[str, Any],
) -> dict[str, Any]:
    """Collect the C12.6 relax-only or defer decision."""

    print_section(
        "C12.6 adsorption DFT execution",
        {
            "job_source": request.get("job_source"),
            "job_count": request.get("job_count", 0),
            "jobs": request.get("jobs", []),
            "warning": (
                "Only adsorption relaxation is supported "
                "in C12.6."
            ),
        },
    )

    while True:
        answer = input(
            "[1] Start adsorption relaxation\n"
            "[2] Defer submission\n> "
        ).strip().lower()

        if answer in {"1", "relax", "relax_only"}:
            return {"mode": "relax_only"}

        if answer in {"2", "defer", ""}:
            return {"mode": "defer"}

        print("Please enter 1 or 2.")


def collect_adsorption_energy_review(
    request: dict[str, Any],
) -> dict[str, Any]:
    """Review C12.7 subtraction and heuristic evaluation."""

    approve: list[str] = []
    reject: list[str] = []
    defer: list[str] = []

    print_section(
        "C12.7 adsorption-energy review",
        {
            "message": request.get("message"),
            "comparison_checks_performed": request.get(
                "comparison_checks_performed"
            ),
        },
    )

    for calculation in request.get("calculations", []):
        identifier = str(
            calculation.get("adsorption_energy_id", "")
        )
        print_section(identifier or "unknown", calculation)
        action = input(
            "[a] approve  [r] reject  [d] defer\n> "
        ).strip().lower()

        if action in {"a", "approve"}:
            approve.append(identifier)
        elif action in {"r", "reject"}:
            reject.append(identifier)
        else:
            defer.append(identifier)

    note = input("Review note, or press Enter:\n> ").strip()
    return {
        "approve": approve,
        "reject": reject,
        "defer": defer,
        "note": note,
    }


def resume_interrupts(
    result: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """处理 LangGraph 中当前支持的人工中断。"""

    while "__interrupt__" in result:
        interrupts = result.get(
            "__interrupt__",
            (),
        )

        if not interrupts:
            raise RuntimeError(
                "LangGraph 返回了空的中断列表。"
            )

        interrupt_value = (
            interrupts[0].value
        )

        if not isinstance(
            interrupt_value,
            dict,
        ):
            raise RuntimeError(
                "无法识别 LangGraph 中断内容。"
            )

        interrupt_type = str(
            interrupt_value.get(
                "type",
                "",
            )
        )

        if interrupt_type == "literature_review_required":
            decision = collect_review_decision(
                interrupt_value
            )
        elif interrupt_type == "candidate_review_required":
            decision = collect_candidate_review_decision(
                interrupt_value
            )
        elif interrupt_type == "c_stage_execution_review_required":
            decision = collect_c_stage_execution_decision(
                interrupt_value
            )
        elif interrupt_type == "c7_dft_upgrade_review_required":
            decision = collect_c7_dft_upgrade_decision(
                interrupt_value
            )
        elif interrupt_type == "slab_review_required":
            decision = collect_slab_review_decision(
                interrupt_value
            )
        elif (
            interrupt_type
            == "adsorption_structure_review_required"
        ):
            decision = (
                collect_adsorption_structure_review(
                    interrupt_value
                )
            )
        elif (
            interrupt_type
            == "adsorption_intermediate_review_required"
        ):
            decision = collect_adsorption_intermediate_review(
                interrupt_value
            )
        elif interrupt_type == "dft_input_review_required":
            decision = collect_dft_input_review_decision(
                interrupt_value
            )
        elif interrupt_type == "bulk_dft_input_review_required":
            decision = collect_dft_input_review_decision(
                interrupt_value
            )
        elif (
            interrupt_type
            == "adsorption_dft_input_review_required"
        ):
            decision = collect_dft_input_review_decision({
                **interrupt_value,
                "stage_label": "C12.5",
            })
        elif interrupt_type == "dft_execution_options_required":
            decision = collect_dft_execution_options(
                interrupt_value
            )
        elif (
            interrupt_type
            == "adsorption_dft_execution_required"
        ):
            decision = collect_adsorption_dft_execution(
                interrupt_value
            )
        elif (
            interrupt_type
            == "adsorption_energy_review_required"
        ):
            decision = collect_adsorption_energy_review(
                interrupt_value
            )
        elif interrupt_type == "remote_upload_review_required":
            decision = collect_remote_upload_review(
                interrupt_value
            )
        elif interrupt_type == "remote_submission_review_required":
            decision = collect_remote_submission_review(
                interrupt_value
            )
        else:
            raise RuntimeError(
                "当前 CLI 不支持的中断类型："
                f"{interrupt_type or 'unknown'}"
            )

        result = graph.invoke(
            Command(
                resume=decision
            ),
            config=config,
        )

    return result


def print_final_result(
    result: dict[str, Any],
) -> None:
    """输出任务结束后的分区结果。"""

    print_section(
        "任务理解",
        result.get(
            "task_analysis",
            {},
        ),
    )

    print_section(
        "Agent 能力边界",
        result.get(
            "capability",
            {},
        ),
    )

    print_section(
        "入口路由",
        result.get(
            "route",
            {},
        ),
    )

    print_section(
        "任务规划",
        result.get(
            "plan",
            {},
        ),
    )

    print_section(
        "联网检索决策",
        result.get(
            "online_search_policy",
            {},
        ),
    )

    merged_result = result.get(
        "merged_literature_result",
        {},
    )

    print_section(
        "合并后的待审查证据概况",
        {
            "local_input_count": (
                merged_result.get(
                    "local_input_count",
                    0,
                )
            ),
            "online_input_count": (
                merged_result.get(
                    "online_input_count",
                    0,
                )
            ),
            "unique_count": (
                merged_result.get(
                    "unique_count",
                    0,
                )
            ),
            "duplicate_count": (
                merged_result.get(
                    "duplicate_count",
                    0,
                )
            ),
            "selected_count": (
                merged_result.get(
                    "selected_count",
                    0,
                )
            ),
        },
    )

    print_section(
        "人工审查结果",
        result.get(
            "literature_review",
            {},
        ),
    )

    print_section(
        "文献入库结果",
        result.get(
            "literature_commit",
            {},
        ),
    )

    summary = result.get(
        "literature_summary",
        {},
    )

    print_section(
        "已接受的文献证据目录",
        summary.get(
            "evidence_catalog",
            [],
        ),
    )

    print_section(
        "RAG 文献总结",
        summary.get(
            "answer",
            "",
        ),
    )

    print_section(
        "C阶段准入结果",
        result.get("c_stage_capability", {}),
    )

    print_section(
        "C1候选约束",
        result.get("candidate_constraints", {}),
    )

    generation = result.get("candidate_generation", {})
    ranked_candidates = generation.get("candidates", [])
    if not isinstance(ranked_candidates, list):
        ranked_candidates = []

    fixed_composition_sampling = (
        generation.get("display_entity") == "fixed_composition_fcc_arrangement"
        or bool(ranked_candidates) and all(
            candidate.get("candidate_kind")
            == "fixed_composition_fcc_arrangement"
            for candidate in ranked_candidates
        )
    )
    generation_title = (
        "固定组成 FCC 原子排布生成摘要"
        if fixed_composition_sampling
        else "候选生成与评分摘要"
    )
    print_section(
        generation_title,
        {
            "status": generation.get("status"),
            "candidate_count": generation.get("candidate_count", 0),
            "review_candidate_count": generation.get(
                "review_candidate_count",
                0,
            ),
            "top_candidates": [
                {
                    "rank": candidate.get("rank"),
                    "candidate_id": candidate.get("candidate_id"),
                    "elements": candidate.get("elements", []),
                    "composition": candidate.get("composition", {}),
                    "total_score": candidate.get("total_score"),
                    "scores": candidate.get("scores", {}),
                }
                for candidate in ranked_candidates[:10]
            ],
        },
    )

    candidate_review = result.get(
        "candidate_review",
        {},
    )

    print_section(
        "候选人工确认结果",
        {
            "status": candidate_review.get("status"),
            "reviewed_candidate_count": (
                candidate_review.get(
                    "reviewed_candidate_count",
                    0,
                )
            ),
            "unreviewed_candidate_count": (
                candidate_review.get(
                    "unreviewed_candidate_count",
                    0,
                )
            ),
            "selected_count": candidate_review.get(
                "selected_count",
                0,
            ),
            "rejected_count": candidate_review.get(
                "rejected_count",
                0,
            ),
            "deferred_count": candidate_review.get(
                "deferred_count",
                0,
            ),
            "selected_ids": [
                candidate.get("candidate_id")
                for candidate in candidate_review.get(
                    "selected",
                    [],
                )
            ],
            "rejected_ids": [
                candidate.get("candidate_id")
                for candidate in candidate_review.get(
                    "rejected",
                    [],
                )
            ],
            "ready_for_structure_modeling": (
                candidate_review.get(
                    "ready_for_structure_modeling",
                    False,
                )
            ),
            "note": candidate_review.get(
                "decision",
                {},
            ).get(
                "note",
                "",
            ),
        },
    )

    print_section(
        (
            "进入后续FCC建模的固定组成原子排布"
            if fixed_composition_sampling
            else "进入后续FCC建模的候选"
        ),
        result.get("selected_candidates", []),
    )

    structure_modeling = result.get(
        "structure_modeling",
        {},
    )

    print_section(
        "C5 FCC体相结构建模",
        {
            "status": structure_modeling.get("status"),
            "selected_candidate_count": (
                structure_modeling.get(
                    "selected_candidate_count",
                    0,
                )
            ),
            "modeled_candidate_count": (
                structure_modeling.get(
                    "modeled_candidate_count",
                    0,
                )
            ),
            "structure_count": structure_modeling.get(
                "structure_count",
                0,
            ),
            "structures": [
                {
                    "structure_id": structure.get(
                        "structure_id"
                    ),
                    "candidate_id": structure.get(
                        "candidate_id"
                    ),
                    "atom_count": structure.get(
                        "atom_count"
                    ),
                    "lattice_constant_a0": structure.get(
                        "lattice_constant_a0"
                    ),
                    "cif_path": structure.get(
                        "cif_path"
                    ),
                    "poscar_path": structure.get(
                        "poscar_path"
                    ),
                    "formation_energy": structure.get(
                        "formation_energy"
                    ),
                    "eligible_for_slab": structure.get(
                        "eligible_for_slab",
                        False,
                    ),
                }
                for structure in structure_modeling.get(
                    "structures",
                    [],
                )
            ],
            "failures": structure_modeling.get(
                "failures",
                [],
            ),
        },
    )

    formation_energy = result.get(
        "formation_energy_evaluation",
        {},
    )
    formation_status = formation_energy.get("status") or "not_executed"

    print_section(
        "C6形成能预测与DFT路由",
        {
            "status": formation_status,
            "reason": formation_energy.get("reason", ""),
            "structure_count": formation_energy.get(
                "structure_count",
                0,
            ),
            "cgcnn_predicted_count": (
                formation_energy.get(
                    "cgcnn_predicted_count",
                    0,
                )
            ),
            "waiting_for_dft_count": (
                formation_energy.get(
                    "waiting_for_dft_count",
                    0,
                )
            ),
            "failed_count": formation_energy.get(
                "failed_count",
                0,
            ),
            "structures": [
                {
                    "structure_id": structure.get(
                        "structure_id"
                    ),
                    "elements": structure.get(
                        "elements",
                        [],
                    ),
                    "route": structure.get(
                        "formation_energy_route"
                    ),
                    "status": structure.get(
                        "formation_energy_status"
                    ),
                    "formation_energy": structure.get(
                        "formation_energy"
                    ),
                    "unit": structure.get(
                        "formation_energy_unit"
                    ),
                    "unsupported_elements": structure.get(
                        "cgcnn_unsupported_elements",
                        [],
                    ),
                }
                for structure in formation_energy.get(
                    "structures",
                    [],
                )
            ],
            "dft_queue": formation_energy.get(
                "dft_queue",
                [],
            ),
            "errors": formation_energy.get(
                "errors",
                [],
            ),
        },
    )

    stability = result.get(
        "stability_screening",
        {},
    )
    stability_status = stability.get("status") or "not_executed"

    print_section(
        "C7稳定性联合筛选",
        {
            "status": stability_status,
            "reason": stability.get("reason", ""),
            "structure_count": stability.get(
                "structure_count",
                0,
            ),
            "passed_count": stability.get(
                "passed_count",
                0,
            ),
            "failed_count": stability.get(
                "failed_count",
                0,
            ),
            "pending_count": stability.get(
                "pending_count",
                0,
            ),
            "criteria": stability.get(
                "criteria",
                {},
            ),
            "structures": [
                {
                    "structure_id": structure.get(
                        "structure_id"
                    ),
                    "formation_energy": structure.get(
                        "formation_energy"
                    ),
                    "formation_energy_pass": structure.get(
                        "formation_energy_pass"
                    ),
                    "delta_percent": structure.get(
                        "delta_percent"
                    ),
                    "delta_pass": structure.get(
                        "delta_pass"
                    ),
                    "omega": structure.get("omega"),
                    "omega_pass": structure.get(
                        "omega_pass"
                    ),
                    "decision": structure.get(
                        "stability_decision"
                    ),
                    "eligible_for_slab": structure.get(
                        "eligible_for_slab",
                        False,
                    ),
                }
                for structure in stability.get(
                    "structures",
                    [],
                )
            ],
            "errors": stability.get("errors", []),
        },
    )

    slab_generation = result.get(
        "slab_generation",
        {},
    )

    if not isinstance(slab_generation, dict) or not slab_generation.get(
        "status"
    ):
        slab_generation = {
            "status": "not_executed",
            "reason": c8_not_executed_reason(result),
        }

    print_section(
        "C8 FCC(111)切面结果",
        {
            "status": slab_generation.get("status"),
            "reason": slab_generation.get("reason", ""),
            "input_structure_count": (
                slab_generation.get(
                    "input_structure_count",
                    0,
                )
            ),
            "slab_count": slab_generation.get(
                "slab_count",
                0,
            ),
            "failure_count": slab_generation.get(
                "failure_count",
                0,
            ),
            "miller_index": slab_generation.get(
                "miller_index",
                [1, 1, 1],
            ),
            "vacuum_angstrom": slab_generation.get(
                "vacuum_angstrom",
                18.0,
            ),
            "slabs": [
                {
                    "slab_id": slab.get("slab_id"),
                    "source_structure_id": slab.get(
                        "source_structure_id"
                    ),
                    "atom_count": slab.get(
                        "atom_count"
                    ),
                    "fixed_atom_count": slab.get(
                        "fixed_atom_count"
                    ),
                    "movable_atom_count": slab.get(
                        "movable_atom_count"
                    ),
                    "cif_path": slab.get("cif_path"),
                    "poscar_path": slab.get(
                        "poscar_path"
                    ),
                }
                for slab in slab_generation.get(
                    "slabs",
                    [],
                )
            ],
            "failures": slab_generation.get(
                "failures",
                [],
            ),
        },
    )

    slab_quality = result.get(
        "slab_quality",
        {},
    )

    print_section(
        "C9 slab 自动质量检查",
        {
            "status": slab_quality.get("status"),
            "input_slab_count": slab_quality.get(
                "input_slab_count",
                0,
            ),
            "passed_count": slab_quality.get(
                "passed_count",
                0,
            ),
            "failed_count": slab_quality.get(
                "failed_count",
                0,
            ),
            "reports": [
                {
                    "slab_id": report.get("slab_id"),
                    "quality_decision": report.get(
                        "quality_decision"
                    ),
                    "minimum_distance_angstrom": (
                        report.get(
                            "minimum_distance_angstrom"
                        )
                    ),
                    "measured_vacuum_angstrom": (
                        report.get(
                            "measured_vacuum_angstrom"
                        )
                    ),
                    "fixed_atom_count": report.get(
                        "fixed_atom_count"
                    ),
                    "movable_atom_count": report.get(
                        "movable_atom_count"
                    ),
                    "failed_checks": report.get(
                        "failed_checks",
                        [],
                    ),
                }
                for report in slab_quality.get(
                    "reports",
                    [],
                )
            ],
        },
    )

    slab_review = result.get(
        "slab_review",
        {},
    )

    print_section(
        "C9 slab 人工确认结果",
        {
            "status": slab_review.get("status"),
            "reviewed_count": slab_review.get(
                "reviewed_count",
                0,
            ),
            "approved_count": slab_review.get(
                "approved_count",
                0,
            ),
            "rejected_count": slab_review.get(
                "rejected_count",
                0,
            ),
            "deferred_count": slab_review.get(
                "deferred_count",
                0,
            ),
            "approved_ids": [
                slab.get("slab_id")
                for slab in slab_review.get(
                    "approved",
                    [],
                )
            ],
            "ready_for_dft": slab_review.get(
                "approved_for_dft",
                False,
            ),
        },
    )

    c6d = result.get(
        "bulk_dft_input_preparation",
        {},
    )

    print_section(
        "C6D bulk DFT 输入文件",
        {
            "status": c6d.get("status"),
            "prepared_job_count": c6d.get(
                "prepared_job_count", 0
            ),
            "failure_count": c6d.get(
                "failure_count", 0
            ),
            "revision_count": result.get(
                "bulk_dft_revision_count", 0
            ),
            "jobs": [
                {
                    "job_id": job.get("job_id"),
                    "structure_id": job.get("structure_id"),
                    "job_dir": job.get("job_dir"),
                    "element_order": job.get("element_order"),
                    "potcar_order": job.get("potcar_order"),
                    "preview_digest": job.get("preview_digest"),
                }
                for job in c6d.get("jobs", [])
            ],
            "failures": c6d.get("failures", []),
        },
    )

    local_preflight = result.get(
        "dft_local_preflight",
        {},
    )

    print_section(
        "C11.2 本地五文件预检查",
        {
            "status": local_preflight.get("status"),
            "job_source": local_preflight.get(
                "job_source"
            ),
            "job_count": local_preflight.get(
                "job_count",
                0,
            ),
            "passed_count": local_preflight.get(
                "passed_count",
                0,
            ),
            "failed_count": local_preflight.get(
                "failed_count",
                0,
            ),
            "jobs": [
                {
                    "job_id": job.get("job_id"),
                    "job_dir": job.get("job_dir"),
                    "passed": job.get(
                        "local_preflight_passed"
                    ),
                    "failed_checks": [
                        error.get("check")
                        for error in job.get(
                            "errors",
                            [],
                        )
                    ],
                }
                for job in local_preflight.get(
                    "jobs",
                    [],
                )
            ],
            "submission_performed": (
                local_preflight.get(
                    "submission_performed",
                    False,
                )
            ),
        },
    )

    cluster_preflight = result.get(
        "cluster_readonly_preflight",
        {},
    )

    print_section(
        "C11.3 cluster read-only preflight",
        {
            "status": cluster_preflight.get(
                "status"
            ),
            "cluster": cluster_preflight.get(
                "cluster",
                {},
            ),
            "job_count": cluster_preflight.get(
                "job_count",
                0,
            ),
            "passed_count": cluster_preflight.get(
                "passed_count",
                0,
            ),
            "failed_count": cluster_preflight.get(
                "failed_count",
                0,
            ),
            "checks": cluster_preflight.get(
                "checks",
                [],
            ),
            "errors": cluster_preflight.get(
                "errors",
                [],
            ),
            "upload_performed": cluster_preflight.get(
                "upload_performed",
                False,
            ),
            "remote_write_performed": (
                cluster_preflight.get(
                    "remote_write_performed",
                    False,
                )
            ),
            "submission_performed": (
                cluster_preflight.get(
                    "submission_performed",
                    False,
                )
            ),
            "next_stage": cluster_preflight.get(
                "next_stage"
            ),
        },
    )

    remote_plan = result.get(
        "remote_execution_plan",
        {},
    )

    print_section(
        "C11.4.1 remote execution plan",
        {
            "status": remote_plan.get("status"),
            "task_id": remote_plan.get("task_id"),
            "job_source": remote_plan.get(
                "job_source"
            ),
            "remote_batch_directory": remote_plan.get(
                "remote_batch_directory"
            ),
            "job_count": remote_plan.get(
                "job_count",
                0,
            ),
            "jobs": [
                {
                    "job_id": job.get("job_id"),
                    "local_job_directory": job.get(
                        "local_job_directory"
                    ),
                    "remote_job_directory": job.get(
                        "remote_job_directory"
                    ),
                    "files": [
                        {
                            "name": file.get("name"),
                            "size_bytes": file.get(
                                "size_bytes"
                            ),
                            "sha256": file.get(
                                "sha256"
                            ),
                        }
                        for file in job.get(
                            "files",
                            [],
                        )
                    ],
                }
                for job in remote_plan.get(
                    "jobs",
                    [],
                )
            ],
            "overwrite_allowed": remote_plan.get(
                "overwrite_allowed",
                False,
            ),
            "remote_write_performed": remote_plan.get(
                "remote_write_performed",
                False,
            ),
            "upload_performed": remote_plan.get(
                "upload_performed",
                False,
            ),
            "submission_performed": remote_plan.get(
                "submission_performed",
                False,
            ),
        },
    )

    upload_review = result.get(
        "remote_upload_review",
        {},
    )
    upload_result = result.get(
        "remote_upload_result",
        {},
    )

    print_section(
        "C11.4.2 remote upload result",
        {
            "review_status": upload_review.get(
                "status"
            ),
            "approved_job_ids": upload_review.get(
                "approved_job_ids",
                [],
            ),
            "status": upload_result.get("status"),
            "approved_count": upload_result.get(
                "approved_count",
                0,
            ),
            "uploaded_count": upload_result.get(
                "uploaded_count",
                0,
            ),
            "verified_count": upload_result.get(
                "verified_count",
                0,
            ),
            "failed_count": upload_result.get(
                "failed_count",
                0,
            ),
            "jobs": [{
                "job_id": job.get("job_id"),
                "remote_job_directory": job.get(
                    "remote_job_directory"
                ),
                "staging_directory": job.get(
                    "staging_directory"
                ),
                "upload_status": job.get(
                    "upload_status"
                ),
                "remote_hash_verified": job.get(
                    "remote_hash_verified",
                    False,
                ),
                "errors": job.get("errors", []),
            } for job in upload_result.get(
                "jobs",
                [],
            )],
            "remote_write_performed": upload_result.get(
                "remote_write_performed",
                False,
            ),
            "upload_performed": upload_result.get(
                "upload_performed",
                False,
            ),
            "submission_performed": upload_result.get(
                "submission_performed",
                False,
            ),
        },
    )

    submission_review = result.get(
        "remote_submission_review",
        {},
    )
    submission_result = result.get(
        "remote_submission_result",
        {},
    )

    print_section(
        "C11.4.3 remote Slurm submission",
        {
            "review_status": submission_review.get(
                "status"
            ),
            "approved_job_ids": submission_review.get(
                "approved_job_ids",
                [],
            ),
            "status": submission_result.get("status"),
            "approved_count": submission_result.get(
                "approved_count",
                0,
            ),
            "submitted_count": submission_result.get(
                "submitted_count",
                0,
            ),
            "unknown_count": submission_result.get(
                "unknown_count",
                0,
            ),
            "failed_count": submission_result.get(
                "failed_count",
                0,
            ),
            "slurm_job_ids": submission_result.get(
                "slurm_job_ids",
                [],
            ),
            "jobs": [{
                "job_id": job.get("job_id"),
                "submission_status": job.get(
                    "submission_status"
                ),
                "slurm_job_id": job.get(
                    "slurm_job_id"
                ),
                "remote_job_directory": job.get(
                    "remote_job_directory"
                ),
            } for job in submission_result.get(
                "jobs",
                [],
            )],
            "automatic_retry_allowed": (
                submission_result.get(
                    "automatic_retry_allowed",
                    False,
                )
            ),
            "next_stage": submission_result.get(
                "next_stage"
            ),
        },
    )

    recording = result.get(
        "submission_recording",
        {},
    )

    print_section(
        "C11.5.1 persisted Slurm jobs",
        {
            "status": recording.get("status"),
            "recorded_count": recording.get(
                "recorded_count",
                0,
            ),
            "new_record_count": recording.get(
                "new_record_count",
                0,
            ),
            "existing_count": recording.get(
                "existing_count",
                0,
            ),
            "failed_count": recording.get(
                "failed_count",
                0,
            ),
            "records": [{
                "slurm_job_id": record.get(
                    "slurm_job_id"
                ),
                "job_id": record.get("job_id"),
                "job_source": record.get(
                    "job_source"
                ),
                "monitoring_status": record.get(
                    "monitoring_status"
                ),
                "remote_job_directory": record.get(
                    "remote_job_directory"
                ),
                "record_path": record.get(
                    "record_path"
                ),
            } for record in recording.get(
                "records",
                [],
            )],
            "latest_manifest_path": recording.get(
                "latest_manifest_path"
            ),
            "next_stage": recording.get(
                "next_stage"
            ),
        },
    )

    c10 = result.get(
        "dft_input_preparation",
        {},
    )

    print_section(
        "C10 revision history",
        {
            "revision_count": result.get(
                "dft_revision_count", 0
            ),
            "latest_validation": result.get(
                "dft_revision_validation", {}
            ),
            "history": result.get(
                "dft_revision_history", []
            ),
        },
    )

    print_section(
        "C10 VASP 计算文件",
        {
            "status": c10.get("status"),
            "prepared_job_count": c10.get(
                "prepared_job_count",
                0,
            ),
            "failure_count": c10.get(
                "failure_count",
                0,
            ),
            "jobs": [
                {
                    "job_id": job.get("job_id"),
                    "job_dir": job.get("job_dir"),
                    "file_count": job.get("file_count"),
                    "element_order": job.get(
                        "element_order"
                    ),
                    "potcar_order": job.get(
                        "potcar_order"
                    ),
                    "submission_ready": job.get(
                        "submission_ready"
                    ),
                }
                for job in c10.get("jobs", [])
            ],
            "failures": c10.get(
                "failures",
                [],
            ),
        },
    )

    print_section(
        "警告",
        result.get(
            "warnings",
            [],
        ),
    )

    print_section(
        "错误",
        result.get(
            "errors",
            [],
        ),
    )

    literature_commit = result.get("literature_commit", {})
    skipped_papers = literature_commit.get("skipped", [])
    if not isinstance(skipped_papers, list):
        skipped_papers = []
    accepted_existing_local_count = sum(
        "无需重复入库" in str(item.get("reason", ""))
        or "已存在" in str(item.get("reason", ""))
        for item in skipped_papers
        if isinstance(item, dict)
    )

    raw_graph_status = result.get("status")
    effective_status = raw_graph_status
    status_candidates = (
        result.get("remote_submission_result", {}),
        result.get("dft_input_preparation", {}),
        result.get("bulk_dft_input_preparation", {}),
        result.get("dft_local_preflight", {}),
        result.get("stability_screening", {}),
        result.get("formation_energy_evaluation", {}),
        result.get("external_structure_ingestion", {}),
    )
    for candidate in status_candidates:
        candidate_status = str(candidate.get("status", "") or "")
        if candidate_status and not candidate_status.endswith("_disabled"):
            effective_status = candidate_status
            break

    print_section(
        "最终状态",
        {
            "task_id": result.get(
                "task_id",
            ),
            "status": effective_status,
            "effective_status": effective_status,
            "raw_graph_status": raw_graph_status,
            "rag_used": summary.get(
                "rag_used",
            ),
            "accepted_evidence_count": (
                summary.get(
                    "evidence_count",
                    0,
                )
            ),
            "newly_stored_paper_count": literature_commit.get(
                "stored_count", 0
            ),
            "accepted_existing_local_paper_count": (
                accepted_existing_local_count
            ),
            "journal_metric_coverage_count": result.get(
                "literature_assertion_extraction", {}
            ).get("journal_metric_coverage_count", 0),
            "journal_metric_missing_count": result.get(
                "literature_assertion_extraction", {}
            ).get("journal_metric_missing_count", 0),
            "generated_candidate_count": (
                result.get(
                    "candidate_generation",
                    {},
                ).get(
                    "candidate_count",
                    0,
                )
            ),
            "selected_candidate_count": len(
                result.get("selected_candidates", [])
            ),
            "structure_modeling_completed": bool(
                result.get("structure_modeling", {}).get(
                    "status"
                ) == "structure_modeling_completed"
                and result.get("structure_modeling", {}).get(
                    "structure_count", 0
                ) > 0
            ),
            "stability_screening_completed": str(
                result.get("stability_screening", {}).get(
                    "status", ""
                )
            ).startswith("stability_screening_completed"),
            "stability_screening_passed": bool(
                result.get("stability_screening", {}).get(
                    "passed_count", 0
                ) > 0
            ),
            "ready_for_slab_generation": bool(
                result.get("stability_screening", {}).get(
                    "passed_count", 0
                ) > 0
            ),
            "workflow_stop_reason": result.get("workflow_stop_reason") or (
                "no_structure_passed_c7_stability_screening"
                if (
                    str(result.get("stability_screening", {}).get(
                        "status", ""
                    )).startswith("stability_screening_completed")
                    and result.get("stability_screening", {}).get(
                        "passed_count", 0
                    ) == 0
                )
                else ""
            ),
        },
    )


def main() -> None:
    """带文献人工审查的 LangGraph 命令行入口。"""

    if hasattr(
        sys.stdout,
        "reconfigure",
    ):
        sys.stdout.reconfigure(
            encoding="utf-8",
            errors="replace",
        )

    parser = argparse.ArgumentParser(
        description=(
            "催化剂科研 Agent "
            "LangGraph 文献审查入口"
        )
    )

    parser.add_argument(
        "question",
        nargs="?",
        help="用户输入的科研问题",
    )

    parser.add_argument(
        "--thread-id",
        default="",
        help="LangGraph 任务线程 ID",
    )

    parser.add_argument(
        "--required-elements",
        nargs="*",
        default=[],
        help="C1 必须包含的元素符号，例如 --required-elements Au Cu",
    )

    parser.add_argument(
        "--preferred-elements",
        nargs="*",
        default=[],
        help="C1 优先考虑的元素符号",
    )

    parser.add_argument(
        "--excluded-elements",
        nargs="*",
        default=[],
        help="C1 禁止使用的元素符号",
    )

    parser.add_argument(
        "--external-structure",
        default="",
        help="External Bulk POSCAR/CIF path to enter C7 directly",
    )
    parser.add_argument(
        "--formation-energy",
        type=float,
        default=None,
        help=(
            "Optional predicted formation energy in eV/atom; when omitted, "
            "the standard C6 CGCNN/DFT route is used"
        ),
    )

    args = parser.parse_args()

    question = (
        args.question
        or input("请输入科研问题：\n> ")
    ).strip()

    if not question:
        raise ValueError(
            "科研问题不能为空。"
        )

    thread_id = (
        args.thread_id.strip()
        or f"task-{uuid.uuid4().hex[:12]}"
    )

    initial_state = {
        "task_id": thread_id,
        "question": question,
        "candidate_user_overrides": {
            "required_elements": args.required_elements,
            "preferred_elements": args.preferred_elements,
            "excluded_elements": args.excluded_elements,
        },
        "external_structure_request": {
            "path": args.external_structure,
            "formation_energy": args.formation_energy,
            "formation_energy_source": "user_provided_prediction",
        },
        "errors": [],
        "warnings": [],
        "retry_count": 0,
        "status": "created",
    }

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    print(
        f"开始运行 LangGraph，"
        f"thread_id={thread_id}"
    )

    result = graph.invoke(
        initial_state,
        config=config,
    )

    result = resume_interrupts(
        result=result,
        config=config,
    )

    print_final_result(result)

    try:
        from app.job_monitor_launcher import launch_job_monitor

        monitor = launch_job_monitor(result)
        if monitor.get("status") == "monitor_launched":
            print(
                "\n已打开独立作业监控窗口："
                + ", ".join(monitor.get("slurm_job_ids", []))
            )
        elif monitor.get("status") == "monitor_already_running":
            print("\n对应作业的监控窗口已经在运行。")
    except Exception as error:
        print(
            "\n作业已提交，但自动打开监控窗口失败："
            f"{type(error).__name__}: {error}"
        )


if __name__ == "__main__":
    main()
