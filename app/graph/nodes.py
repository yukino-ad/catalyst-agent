from __future__ import annotations

import os
from typing import Any

from langgraph.types import interrupt

from app.graph.services import GraphServices, create_services
from app.graph.state import CatalystState
from app.domain.direct_c_stage import classify_direct_c_stage_request
from app.domain.external_structure_input import ExternalStructureInputService
from app.domain.cgcnn_training_manager import CGCNNTrainingManager
from tools.literature.retry_support import (
    accepted_five_metal_sets,
    literature_verification_level,
    paper_identities,
)


# 图加载时创建一次，后续节点共享这些服务。
services: GraphServices = create_services()
external_structure_input_service = ExternalStructureInputService()
cgcnn_training_manager = CGCNNTrainingManager()

CANDIDATE_REVIEW_LIMIT = 10


def _literature_search_queries(
    state: CatalystState,
    primary_query: str,
) -> list[str]:
    task = state.get("task_analysis", {})
    reaction = str(task.get("reaction_family", "") or "electrocatalysis")
    round_number = int(state.get("literature_search_round", 1) or 1)
    variants = (
        "quinary high entropy alloy electrocatalyst explicit composition",
        "five-metal high entropy alloy electrocatalyst explicit composition",
        "five-component high entropy alloy electrocatalyst",
        "quinary HEA electrocatalyst explicit element composition",
    )
    offset = (round_number - 1) % len(variants)
    ordered = variants[offset:] + variants[:offset]
    queries = [
        f"{reaction} {variant}".strip()
        for variant in ordered
    ]
    concise_primary = " ".join(primary_query.split()[:12])
    queries.insert(0, f"{concise_primary} quinary explicit composition".strip())
    used = {
        str(query).strip().lower()
        for entry in state.get("literature_search_history", [])
        if isinstance(entry, dict)
        for query in entry.get("queries", [])
    }
    unique = []
    for query in queries:
        if query.lower() not in used and query not in unique:
            unique.append(query[:500])
    return unique[:5]

def task_analysis_node(
    state: CatalystState,
) -> dict[str, Any]:
    """识别反应、产物、材料类型和用户所需工具。"""

    question = state.get(
        "question",
        "",
    ).strip()

    if not question:
        return {
            "status": "task_analysis_failed",
            "errors": _append_message(
                state=state,
                node="task_analysis",
                error_type="missing_question",
                message="用户科研问题不能为空。",
            ),
        }

    try:
        analysis = services.analyzer.analyze(
            question
        )

        overrides = state.get(
            "candidate_user_overrides",
            {},
        )
        required_elements = (
            overrides.get("required_elements", [])
            if isinstance(overrides, dict)
            else []
        )
        context, validation = (
            services.task_context_builder.build(
                question=question,
                analysis=analysis,
                user_overrides=(
                    overrides
                    if isinstance(overrides, dict)
                    else {}
                ),
            )
        )
        analysis = services.task_context_builder.apply_to_analysis(
            analysis,
            context,
        )
        external_request = external_structure_input_service.resolve_request(
            question,
            state.get("external_structure_request", {}),
        )
        direct_c_stage = classify_direct_c_stage_request(question, analysis)
        if direct_c_stage["requested"]:
            analysis["needs_candidate_design"] = False
            analysis["needs_structure_modeling"] = True
            analysis["structured_candidate_request"] = True
            analysis["fixed_composition_sampling"] = True
            analysis["scientific_scope"] = (
                "reaction_agnostic_bulk_stability"
            )
            overrides = dict(overrides) if isinstance(overrides, dict) else {}
            overrides["required_elements"] = direct_c_stage[
                "specified_elements"
            ]
            overrides["required_elements_source"] = (
                "explicit_direct_c_request"
            )
            analysis["candidate_generation_override"] = {
                "active": True,
                "mode": "fixed_composition_structure_sampling",
                "reason": (
                    "普通候选设计能力未启用；用户明确指定的五元组成"
                    "允许直接进入 FCC 建模候选流程。"
                ),
            }
        analysis["online_preference"] = context["online_preference"]
        analysis["evidence_requirements"] = context[
            "evidence_requirements"
        ]
        analysis["unresolved_fields"] = context["unresolved_fields"]
        if required_elements:
            analysis["structured_candidate_request"] = True

        return {
            "task_analysis": analysis,
            "canonical_task_context": context,
            "task_context_validation": validation,
            "direct_c_stage": direct_c_stage,
            "external_structure_request": external_request,
            "candidate_user_overrides": overrides,
            "reaction_profile": analysis[
                "reaction_profile"
            ],
            "status": "task_analyzed",
        }

    except Exception as error:
        return {
            "status": "task_analysis_failed",
            "errors": _append_error(
                state=state,
                node="task_analysis",
                error=error,
            ),
        }


def external_structure_input_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Inject a supplied POSCAR/CIF and predicted energy into standard C7."""

    try:
        result = external_structure_input_service.prepare(
            state.get("external_structure_request", {})
        )
        structure = result["structure"]
        update = {
            "external_structure_ingestion": result,
            "bulk_structures": [structure],
            "c_stage_execution_mode": "dft_validation",
            "status": result["status"],
        }
        if structure.get("formation_energy") is not None:
            update.update({
                "formation_energy_structures": [structure],
                "selected_formation_energy_source": "external_user_provided",
                "selected_formation_energy_structures": [structure],
                "formation_energy_evaluation": {
                    "schema_version": "c6.0",
                    "stage": "c6",
                    "status": "formation_energy_completed_external_input",
                    "structure_count": 1,
                    "cgcnn_predicted_count": 1,
                    "waiting_for_dft_count": 0,
                    "structures": [structure],
                    "dft_queue": [],
                    "next_stage": "c7_stability_screening",
                },
                "dft_formation_energy_queue": [],
            })
        return update
    except Exception as error:
        return {
            "external_structure_ingestion": {
                "schema_version": "c-external-structure-v1",
                "stage": "external_structure_input",
                "status": "external_structure_input_failed",
                "error_type": type(error).__name__,
                "message": str(error),
            },
            "formation_energy_structures": [],
            "slab_eligible_structures": [],
            "formation_energy_evaluation": {
                "schema_version": "c6.0",
                "stage": "c6",
                "status": "not_executed",
                "reason": str(error),
                "structure_count": 0,
                "cgcnn_predicted_count": 0,
                "waiting_for_dft_count": 0,
                "failed_count": 0,
                "structures": [],
                "dft_queue": [],
                "errors": [],
            },
            "stability_screening": {
                "schema_version": "c7.0",
                "stage": "c7",
                "status": "not_executed",
                "reason": "External structure ingestion failed before C6.",
                "structure_count": 0,
                "passed_count": 0,
                "failed_count": 0,
                "pending_count": 0,
                "criteria": {},
                "structures": [],
                "errors": [],
            },
            "workflow_stop_reason": "external_structure_input_failed",
            "status": "external_structure_input_failed",
            "errors": _append_error(state, "external_structure_input", error),
        }


def capability_gate_node(
    state: CatalystState,
) -> dict[str, Any]:
    """检查当前 Agent 是否具备任务需要的工具能力。"""

    analysis = state.get(
        "task_analysis",
        {},
    )

    if not analysis:
        return {
            "status": "capability_check_failed",
            "errors": _append_message(
                state=state,
                node="capability_gate",
                error_type="missing_task_analysis",
                message="能力检查前没有任务分析结果。",
            ),
        }

    try:
        capability = (
            services.capability_gate.evaluate(
                analysis
            )
        )

        warnings = list(
            state.get("warnings", [])
        )

        for warning in capability.get(
            "warnings",
            [],
        ):
            if warning not in warnings:
                warnings.append(warning)

        return {
            "capability": capability,
            "warnings": warnings,
            "status": "capability_checked",
        }

    except Exception as error:
        return {
            "status": "capability_check_failed",
            "errors": _append_error(
                state=state,
                node="capability_gate",
                error=error,
            ),
        }

def router_node(state: CatalystState) -> dict[str, Any]:
    """理解用户意图，并决定是否需要文献 RAG。"""

    question = state.get("question", "").strip()

    if not question:
        return {
            "route": {
                "intent": "",
                "use_rag": False,
                "rag_reason": "用户没有提供科研问题。",
                "rag_query": "",
                "rag_focus": [],
                "requested_actions": [],
                "router_mode": "validation",
            },
            "status": "invalid_question",
            "errors": _append_message(
                state=state,
                node="router",
                error_type="missing_question",
                message="用户科研问题不能为空。",
            ),
        }

    try:
        route = services.router.route(
            question,
            state.get("canonical_task_context", {}),
        )

        return {
            "route": route,
            "status": "routed",
        }

    except Exception as error:
        return {
            "route": {
                "intent": question,
                "use_rag": False,
                "rag_reason": "入口路由执行失败，暂时跳过 RAG。",
                "rag_query": "",
                "rag_focus": [],
                "requested_actions": [],
                "router_mode": "error_fallback",
            },
            "status": "router_failed",
            "errors": _append_error(
                state=state,
                node="router",
                error=error,
            ),
        }


def planner_node(state: CatalystState) -> dict[str, Any]:
    """将用户问题转换为结构化科研计划。"""

    question = state.get("question", "").strip()

    if not question:
        return {
            "status": "planning_failed",
            "errors": _append_message(
                state=state,
                node="planner",
                error_type="missing_question",
                message="Planner 没有收到用户科研问题。",
            ),
        }

    try:
        plan = services.planner.plan(
            question,
            state.get("canonical_task_context", {}),
        )
        route = state.get("route", {})

        original_keywords = plan.get("keywords", [])
        route_focus = route.get("rag_focus", [])

        plan["keywords"] = _unique_strings(
            [
                *original_keywords,
                *route_focus,
            ]
        )

        return {
            "plan": plan,
            "status": "planned",
        }

    except Exception as error:
        return {
            "status": "planning_failed",
            "errors": _append_error(
                state=state,
                node="planner",
                error=error,
            ),
        }


def rag_node(state: CatalystState) -> dict[str, Any]:
    """检索文献并生成带 E1/E2 引用的总结。"""

    question = state.get("question", "").strip()
    route = state.get("route", {})
    plan = state.get("plan", {})

    rag_query = str(
        route.get("rag_query", "")
    ).strip() or question

    if not plan:
        return {
            "status": "rag_failed",
            "errors": _append_message(
                state=state,
                node="rag",
                error_type="missing_plan",
                message="执行 RAG 前没有找到任务规划结果。",
            ),
        }

    try:
        rag_result = services.rag.run(
            question=rag_query,
            plan=plan,
            top_k=5,
        )

        evidence = rag_result.get(
            "evidence",
            [],
        )

        return {
            "rag_result": rag_result,
            "papers": evidence,
            "status": (
                "literature_retrieved"
                if evidence
                else "literature_not_found"
            ),
        }

    except Exception as error:
        return {
            "rag_result": {
                "evidence": [],
                "synthesis": {
                    "answer": "",
                    "citations": [],
                    "mode": "rag_error",
                },
            },
            "papers": [],
            "status": "rag_failed",
            "errors": _append_error(
                state=state,
                node="rag",
                error=error,
            ),
        }


def literature_evidence_node(
    state: CatalystState,
) -> dict[str, Any]:
    """
    执行 B2-B5 文献证据准备流程。

    B2：本地检索；
    B3：判断是否需要联网；
    B4：按需少量查询 Crossref/Semantic Scholar；
    B5：合并、去重、评分和重排。

    本节点不会修改正式文献数据库。
    """

    question = str(
        state.get("question", "") or ""
    ).strip()

    route = state.get("route", {})
    plan = state.get("plan", {})
    task_analysis = state.get(
        "task_analysis",
        {},
    )

    rag_query = str(
        route.get("rag_query", "") or ""
    ).strip() or question

    keywords = _unique_strings(
        plan.get("keywords", [])
    )
    search_round = int(
        state.get("literature_search_round", 1) or 1
    )
    excluded_identities = set(
        state.get("rejected_literature_identities", [])
    )

    if not question:
        return {
            "papers": [],
            "status": (
                "literature_evidence_failed"
            ),
            "errors": _append_message(
                state=state,
                node="literature_evidence",
                error_type="missing_question",
                message=(
                    "文献证据准备节点没有收到"
                    "用户科研问题。"
                ),
            ),
        }

    try:
        print("[B2] Recalling local literature (target: 100, preselect: 60).", flush=True)
        local_result = (
            services.local_retriever.retrieve(
                query=rag_query,
                keywords=keywords,
                task_analysis=task_analysis,
                recall_count=100,
                final_count=60,
            )
        )
        print(
            "[B2] Local recall completed: "
            f"{local_result.get('selected_count', len(local_result.get('selected', [])))} selected.",
            flush=True,
        )

        policy_result = (
            services.online_policy.evaluate(
                local_result=local_result,
                task_analysis=task_analysis,
                question=question,
            )
        )

        print(
            f"[B3] Online policy: {policy_result.get('decision', 'unknown')}.",
            flush=True,
        )

        primary_query = services.online_retriever.build_query(
            question=question,
            task_analysis=task_analysis,
            keywords=keywords,
        )
        search_queries = _literature_search_queries(state, primary_query)
        online_budget = policy_result.get("online_budget", {})
        max_queries = int(online_budget.get("max_queries", 1) or 1)
        search_queries = search_queries[:max_queries]

        online_result = (
            services.online_retriever.retrieve(
                policy_result=policy_result,
                question=question,
                task_analysis=task_analysis,
                keywords=keywords,
                per_page=int(online_budget.get("per_page", 5) or 5),
                mailto=os.getenv(
                    "CROSSREF_MAILTO",
                    "",
                ),
                search_queries=search_queries,
                excluded_identities=excluded_identities,
            )
        )

        kimi_verification = services.kimi_crossref_verifier.verify(
            papers=online_result.get("candidates", []),
            task_analysis=task_analysis,
            question=question,
        )
        online_result = {
            **online_result,
            "candidates": kimi_verification.get("papers", []),
            "kimi_web_search_performed": kimi_verification.get(
                "required_tools_called", False
            ),
            "kimi_cross_verified_count": kimi_verification.get(
                "mutually_verified_count", 0
            ),
        }


        if (
            policy_result.get("decision") == "online_required"
            and online_result.get("status") == "online_failed"
        ):
            warnings = _unique_strings([
                *state.get("warnings", []),
                *policy_result.get("warnings", []),
                *online_result.get("warnings", []),
            ])
            return {
                "local_literature_result": local_result,
                "online_search_policy": policy_result,
                "online_literature_result": online_result,
                "kimi_crossref_verification": kimi_verification,
                "merged_literature_result": {
                    "status": "skipped_online_failure",
                    "selected": [],
                    "selected_count": 0,
                },
                "literature_search_round": search_round,
                "literature_max_search_rounds": int(
                    state.get("literature_max_search_rounds", 3) or 3
                ),
                "papers": [],
                "warnings": warnings,
                "status": "literature_online_search_failed",
            }

        print(
            "[B5] Merging, deduplicating, and scoring local and online papers.",
            flush=True,
        )
        merged_result = (
            services.evidence_merger.merge(
                local_result=local_result,
                online_result=online_result,
                question=question,
                task_analysis=task_analysis,
                keywords=keywords,
                final_count=30,
                excluded_identities=excluded_identities,
            )
        )

        candidates = merged_result.get(
            "selected",
            [],
        )
        print(
            f"[B5] Prepared {len(candidates)} papers for claim extraction.",
            flush=True,
        )

        warnings = _unique_strings(
            [
                *state.get("warnings", []),
                *policy_result.get(
                    "warnings",
                    [],
                ),
                *online_result.get(
                    "warnings",
                    [],
                ),
                *kimi_verification.get(
                    "warnings",
                    [],
                ),
                *merged_result.get(
                    "warnings",
                    [],
                ),
            ]
        )

        return {
            "local_literature_result": (
                local_result
            ),
            "online_search_policy": (
                policy_result
            ),
            "online_literature_result": (
                online_result
            ),
            "kimi_crossref_verification": (
                kimi_verification
            ),
            "merged_literature_result": (
                merged_result
            ),
            "literature_search_round": search_round,
            "literature_max_search_rounds": int(
                state.get("literature_max_search_rounds", 3) or 3
            ),
            # 审查前暂存 B5 候选，之后由接受项覆盖。
            "papers": candidates,
            "warnings": warnings,
            "status": (
                "literature_evidence_prepared"
                if candidates
                else "literature_evidence_empty"
            ),
        }

    except Exception as error:
        policy_result = locals().get("policy_result", {
            "use_online_search": True,
            "decision": "online_required",
        })
        online_result = locals().get("online_result", {
            "status": "online_failed",
            "candidate_count": 0,
            "candidates": [],
            "search_queries": locals().get("search_queries", []),
            "warnings": [f"{type(error).__name__}: {error}"],
        })
        return {
            "local_literature_result": locals().get("local_result", {}),
            "online_search_policy": policy_result,
            "online_literature_result": online_result,
            "merged_literature_result": {
                "status": "failed",
                "selected": [],
            },
            "papers": [],
            "status": (
                "literature_evidence_failed"
            ),
            "errors": _append_error(
                state=state,
                node="literature_evidence",
                error=error,
            ),
        }


def literature_assertion_extraction_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Run B1 final extraction and scoring after B5 deduplication."""

    merged = state.get("merged_literature_result", {})
    candidates = merged.get("selected", [])
    if not isinstance(candidates, list) or not candidates:
        return {
            "literature_assertion_extraction": {
                "schema_version": "b1-extraction-v1",
                "status": "literature_assertion_extraction_empty",
                "paper_count": 0,
                "papers": [],
            },
            "status": "literature_assertion_extraction_empty",
        }
    try:
        result = services.assertion_extraction.process(
            candidates, state.get("task_analysis", {})
        )
        extracted_papers = result["papers"]
        review_candidates = []
        b6_ineligible = [
            {
                **item,
                "b6_exclusion_reasons": item.get("reasons", []),
            }
            for item in result.get("prefilter_rejected", [])
            if isinstance(item, dict)
        ]
        for paper in extracted_papers:
            quality = paper.get("evidence_quality", {})
            eligible = bool(
                quality.get("reaction_direct", False)
                and quality.get("hea_direct", False)
                and quality.get("composition_element_count", 0) == 5
            )
            if eligible:
                review_candidates.append(paper)
            else:
                rejected = dict(paper)
                rejected["b6_exclusion_reasons"] = [
                    reason
                    for condition, reason in (
                        (
                            quality.get("reaction_direct", False),
                            "target_reaction_not_explicit",
                        ),
                        (
                            quality.get("hea_direct", False),
                            "high_entropy_identity_not_explicit",
                        ),
                        (
                            quality.get("composition_element_count", 0) == 5,
                            "explicit_five_metal_composition_not_found",
                        ),
                    )
                    if not condition
                ]
                b6_ineligible.append(rejected)

        for index, paper in enumerate(review_candidates, 1):
            paper["evidence_id"] = f"E{index}"
            for assertion_index, assertion in enumerate(
                paper.get("assertions", []), 1
            ):
                assertion["assertion_id"] = f"E{index}::A{assertion_index}"

        updated_merged = dict(merged)
        updated_merged["selected"] = review_candidates
        updated_merged["selected_count"] = len(review_candidates)
        updated_merged["b6_ineligible"] = b6_ineligible
        updated_merged["b6_ineligible_count"] = len(b6_ineligible)
        updated_merged["b1_final_scoring"] = {
            "status": result["status"],
            "cache_hit_count": result["cache_hit_count"],
            "failure_count": result["failure_count"],
            "llm_fallback_count": result.get("llm_fallback_count", 0),
            "llm_errors": result.get("llm_errors", []),
            "journal_metric_coverage_count": result.get(
                "journal_metric_coverage_count", 0
            ),
            "journal_metric_missing_count": result.get(
                "journal_metric_missing_count", 0
            ),
        }
        warnings = list(state.get("warnings", []))
        if result.get("llm_fallback_count", 0):
            warnings.append(
                "B1 的部分 Kimi 断言抽取失败，已使用确定性规则回退；"
                "具体原因见 literature_assertion_extraction.llm_errors。"
            )
        return {
            "literature_assertion_extraction": result,
            "merged_literature_result": updated_merged,
            "papers": review_candidates,
            "warnings": _unique_strings(warnings),
            "status": result["status"],
        }
    except Exception as error:
        return {
            "literature_assertion_extraction": {
                "status": "literature_assertion_extraction_failed",
                "papers": candidates,
                "failures": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
            },
            "status": "literature_assertion_extraction_failed",
            "errors": _append_error(state, "literature_assertion_extraction", error),
        }


def literature_online_failure_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Stop B-stage cleanly when mandatory online retrieval is unavailable."""

    online = state.get("online_literature_result", {})
    warnings = _unique_strings([
        *state.get("warnings", []),
        *online.get("warnings", []),
        "B4 online retrieval failed; B5, Kimi extraction, B6, and C-stage were not run.",
    ])
    return {
        "literature_evidence_gap": {
            "schema_version": "b-online-failure-v1",
            "status": "literature_online_search_failed",
            "reason": (
                "crossref_rate_limited"
                if any("429" in warning for warning in online.get("warnings", []))
                else "online_retrieval_unavailable"
            ),
            "retryable": True,
            "can_enter_b5": False,
            "can_enter_c_stage": False,
            "search_queries": online.get("search_queries", []),
            "errors": online.get("warnings", []),
        },
        "papers": [],
        "warnings": warnings,
        "status": "literature_online_search_failed",
    }


def literature_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """暂停 LangGraph，等待人工提交文献审查决定。"""

    merged_result = state.get(
        "merged_literature_result",
        {},
    )

    candidates = merged_result.get(
        "selected",
        [],
    )

    if not isinstance(candidates, list):
        candidates = []

    # 没有候选时不需要中断流程。
    if not candidates:
        review_result = (
            services.review_gate.review(
                candidates=[],
                decision={
                    "accept": [],
                    "reject": [],
                    "defer": [],
                    "note": (
                        "没有候选论文，"
                        "无需人工审查。"
                    ),
                },
            )
        )

        return {
            "literature_review": review_result,
            "accepted_literature_assertions": review_result.get(
                "accepted_assertions", []
            ),
            "papers": [],
            "status": (
                "literature_review_skipped"
            ),
        }

    review_request = {
        "type": (
            "literature_review_required"
        ),
        "message": (
            "请人工检查论文标题、DOI、"
            "摘要原文和版本信息。"
        ),
        "task_id": state.get(
            "task_id",
            "",
        ),
        "question": state.get(
            "question",
            "",
        ),
        "instructions": {
            "accept": (
                "允许本轮 RAG 使用；"
                "纯在线论文可在 B6.3 入库。"
            ),
            "reject": (
                "本轮不使用，也不入库。"
            ),
            "defer": (
                "暂缓判断，本轮不使用。"
            ),
            "default": (
                "未分类论文自动进入 defer。"
            ),
        },
        "candidates": [
            _review_candidate(paper)
            for paper in candidates
        ],
    }

    # LangGraph 使用 GraphInterrupt 作为正常暂停信号，
    # 因此 interrupt 不能放在通用异常捕获中。
    decision = interrupt(
        review_request
    )

    try:
        review_result = (
            services.review_gate.review(
                candidates=candidates,
                decision=decision,
            )
        )

        accepted = review_result.get(
            "accepted",
            [],
        )

        warnings = _unique_strings(
            [
                *state.get("warnings", []),
                *review_result.get(
                    "warnings",
                    [],
                ),
            ]
        )

        return {
            "literature_review": review_result,
            "accepted_literature_assertions": review_result.get(
                "accepted_assertions", []
            ),
            # 仅人工接受的证据可以进入后续 RAG。
            "papers": accepted,
            "warnings": warnings,
            "status": (
                "literature_review_completed"
            ),
        }

    except Exception as error:
        return {
            "literature_review": {
                "status": "review_failed",
                "accepted": [],
                "rejected": [],
                "deferred": candidates,
            },
            "papers": [],
            "status": (
                "literature_review_failed"
            ),
            "errors": _append_error(
                state=state,
                node="literature_review",
                error=error,
            ),
        }


def literature_commit_node(
    state: CatalystState,
) -> dict[str, Any]:
    """
    将人工接受的纯在线论文受控写入本地数据库。

    本地论文和 local+online 合并记录不会重复写入。
    被拒绝或暂缓的论文不会写入。
    """

    review_result = state.get(
        "literature_review",
        {},
    )

    if (
        review_result.get("status")
        != "review_completed"
    ):
        return {
            "literature_commit": {
                "status": "commit_skipped",
                "database_count_before": None,
                "database_count_after": None,
                "stored_count": 0,
                "skipped_count": 0,
                "error_count": 0,
                "stored": [],
                "skipped": [],
                "errors": [],
                "reason": (
                    "人工审查尚未成功完成，"
                    "禁止执行文献入库。"
                ),
            },
            "status": (
                "literature_commit_skipped"
            ),
        }

    try:
        commit_result = (
            services.review_gate.commit_accepted(
                review_result
            )
        )

        warnings = list(
            state.get("warnings", [])
        )

        if commit_result.get(
            "error_count",
            0,
        ):
            warning = (
                "部分人工接受的在线论文入库失败，"
                "请检查 literature_commit.errors。"
            )

            if warning not in warnings:
                warnings.append(warning)

        return {
            "literature_commit": commit_result,
            "warnings": warnings,
            "status": commit_result.get(
                "status",
                "commit_completed",
            ),
        }

    except Exception as error:
        return {
            "literature_commit": {
                "status": "commit_failed",
                "database_count_before": None,
                "database_count_after": None,
                "stored_count": 0,
                "skipped_count": 0,
                "error_count": 1,
                "stored": [],
                "skipped": [],
                "errors": [
                    {
                        "error_type": (
                            type(error).__name__
                        ),
                        "message": str(error),
                    }
                ],
            },
            "status": (
                "literature_commit_failed"
            ),
            "errors": _append_error(
                state=state,
                node="literature_commit",
                error=error,
            ),
        }


def literature_retry_prepare_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Persist B6 decisions and prepare a distinct online-search round."""

    review = state.get("literature_review", {})
    round_number = int(state.get("literature_search_round", 1) or 1)
    max_rounds = int(state.get("literature_max_search_rounds", 3) or 3)

    rejected = review.get("rejected", [])
    if not isinstance(rejected, list):
        rejected = []
    identities = set(state.get("rejected_literature_identities", []))
    for paper in rejected:
        if isinstance(paper, dict):
            identities.update(paper_identities(paper))

    accepted_papers = list(state.get("accepted_literature_papers", []))
    known_papers = {
        tuple(sorted(paper_identities(paper)))
        for paper in accepted_papers
        if isinstance(paper, dict)
    }
    for paper in review.get("accepted", []):
        if not isinstance(paper, dict):
            continue
        identity = tuple(sorted(paper_identities(paper)))
        if identity not in known_papers:
            accepted_papers.append(paper)
            known_papers.add(identity)

    assertion_history = list(
        state.get("accepted_literature_assertion_history", [])
    )
    assertion_history.extend(state.get("accepted_literature_assertions", []))

    online = state.get("online_literature_result", {})
    history = list(state.get("literature_search_history", []))
    history.append({
        "round": round_number,
        "queries": online.get("search_queries", []),
        "online_status": online.get("status", ""),
        "raw_online_count": online.get("candidate_count", 0),
        "excluded_count": online.get("excluded_previous_rejections", 0),
        "review_candidate_count": review.get("candidate_count", 0),
        "accepted_count": review.get("accepted_count", 0),
        "rejected_count": review.get("rejected_count", 0),
        "deferred_count": review.get("deferred_count", 0),
    })

    all_rejected = (
        int(review.get("candidate_count", 0) or 0) > 0
        and int(review.get("accepted_count", 0) or 0) == 0
        and int(review.get("deferred_count", 0) or 0) == 0
        and int(review.get("rejected_count", 0) or 0)
        == int(review.get("candidate_count", 0) or 0)
    )
    return {
        "literature_search_round": min(round_number + 1, max_rounds),
        "literature_max_search_rounds": max_rounds,
        "literature_search_history": history,
        "rejected_literature_identities": sorted(identities),
        "accepted_literature_papers": accepted_papers,
        "accepted_literature_assertion_history": assertion_history,
        "literature_retry_plan": {
            "status": "literature_retry_ready",
            "next_round": min(round_number + 1, max_rounds),
            "reason": (
                "all_candidates_explicitly_rejected"
                if all_rejected
                else "accepted_evidence_has_no_eligible_five_metal_set"
            ),
            "required_evidence": [
                "explicit five-metal composition",
                "explicit high-entropy-alloy identity in the same paper",
                "explicit target-reaction relevance",
            ],
            "excluded_identity_count": len(identities),
        },
        "literature_review": {},
        "accepted_literature_assertions": [],
        "papers": [],
        "status": "literature_retry_ready",
    }


def literature_review_finalize_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Persist the final B6 round, including rejected-paper exclusions."""

    review = state.get("literature_review", {})
    identities = set(state.get("rejected_literature_identities", []))
    for paper in review.get("rejected", []):
        if isinstance(paper, dict):
            identities.update(paper_identities(paper))

    accepted_papers = list(state.get("accepted_literature_papers", []))
    accepted_papers.extend(
        paper for paper in review.get("accepted", [])
        if isinstance(paper, dict)
    )
    deduplicated_papers = []
    seen = set()
    for paper in accepted_papers:
        identity = tuple(sorted(paper_identities(paper)))
        if identity in seen:
            continue
        seen.add(identity)
        deduplicated_papers.append(paper)

    assertion_history = [
        *state.get("accepted_literature_assertion_history", []),
        *state.get("accepted_literature_assertions", []),
    ]
    history = list(state.get("literature_search_history", []))
    online = state.get("online_literature_result", {})
    current_round = int(state.get("literature_search_round", 1) or 1)
    if not history or history[-1].get("round") != current_round:
        history.append({
            "round": current_round,
            "queries": online.get("search_queries", []),
            "online_status": online.get("status", ""),
            "raw_online_count": online.get("candidate_count", 0),
            "excluded_count": online.get("excluded_previous_rejections", 0),
            "review_candidate_count": review.get("candidate_count", 0),
            "accepted_count": review.get("accepted_count", 0),
            "rejected_count": review.get("rejected_count", 0),
            "deferred_count": review.get("deferred_count", 0),
        })
    return {
        "rejected_literature_identities": sorted(identities),
        "accepted_literature_papers": deduplicated_papers,
        "accepted_literature_assertion_history": assertion_history,
        "literature_search_history": history,
        "status": "literature_review_history_finalized",
    }


def reviewed_rag_node(
    state: CatalystState,
) -> dict[str, Any]:
    """只使用人工接受的论文生成 RAG 总结。"""

    question = str(
        state.get("question", "") or ""
    ).strip()

    plan = state.get("plan", {})
    review_result = state.get(
        "literature_review",
        {},
    )

    accepted = list(state.get("accepted_literature_papers", []))

    if not isinstance(accepted, list):
        accepted = []

    if not accepted:
        rag_result = {
            "evidence": [],
            "synthesis": {
                "answer": (
                    "本轮没有人工接受的文献证据，"
                    "因此不生成材料结论。"
                ),
                "citations": [],
                "mode": (
                    "no_accepted_evidence"
                ),
            },
        }

        return {
            "rag_result": rag_result,
            "papers": [],
            "status": (
                "reviewed_rag_no_evidence"
            ),
        }

    try:
        synthesis = services.rag.answer(
            question=question,
            plan=plan,
            evidence=accepted,
        )

        return {
            "rag_result": {
                "evidence": accepted,
                "synthesis": synthesis,
            },
            "papers": accepted,
            "status": (
                "reviewed_rag_completed"
            ),
        }

    except Exception as error:
        return {
            "rag_result": {
                "evidence": accepted,
                "synthesis": {
                    "answer": (
                        "文献已经完成人工审查，"
                        "但 RAG 总结生成失败。"
                    ),
                    "citations": [],
                    "mode": "rag_error",
                },
            },
            "papers": accepted,
            "status": (
                "reviewed_rag_failed"
            ),
            "errors": _append_error(
                state=state,
                node="reviewed_rag",
                error=error,
            ),
        }


def skip_rag_node(state: CatalystState) -> dict[str, Any]:
    """Router 判断不需要检索时，生成统一的空结果。"""

    route = state.get("route", {})

    reason = str(
        route.get(
            "rag_reason",
            "入口路由判断本次任务不需要文献检索。",
        )
    ).strip()

    rag_result = {
        "evidence": [],
        "synthesis": {
            "answer": f"本次任务跳过文献检索：{reason}",
            "citations": [],
            "mode": "router_skipped",
        },
    }

    return {
        "rag_result": rag_result,
        "papers": [],
        "status": "rag_skipped",
    }


def literature_summary_node(
    state: CatalystState,
) -> dict[str, Any]:
    """将 RAG 输出转换成后续节点可以直接使用的统一格式。"""

    route = state.get("route", {})
    rag_result = state.get("rag_result", {})
    papers = state.get("papers", [])

    synthesis = rag_result.get(
        "synthesis",
        {},
    )

    evidence_catalog = []

    for index, paper in enumerate(
        papers,
        start=1,
    ):
        evidence_id = (
            paper.get("evidence_id")
            or f"E{index}"
        )

        evidence_catalog.append(
            {
                "evidence_id": evidence_id,
                "paper_id": paper.get(
                    "paper_id",
                    "",
                ),
                "title": paper.get(
                    "title",
                    "未提供论文标题",
                ),
                "year": paper.get("year"),
                "journal": paper.get(
                    "journal",
                    "",
                ),
                "doi": paper.get(
                    "doi",
                    "",
                ),
                "url": paper.get(
                    "url",
                    "",
                ),
                "abstract": paper.get(
                    "abstract",
                    "",
                ),
                "elements": paper.get(
                    "elements",
                    [],
                ),
                "adsorbates": paper.get(
                    "adsorbates",
                    [],
                ),
                "score": paper.get(
                    "score",
                    0,
                ),
                "retrieval_origin": paper.get(
                    "retrieval_origin",
                    "",
                ),
                "review_status": paper.get(
                    "review_status",
                    "",
                ),
                "evidence_quality": paper.get(
                    "evidence_quality",
                    {},
                ),
                "version_info": paper.get(
                    "version_info",
                    {},
                ),
            }
        )

    warnings = list(
        state.get("warnings", [])
    )

    if (
        route.get("use_rag")
        and not evidence_catalog
    ):
        warning = (
            "Router 要求使用 RAG，"
            "但本地数据库没有返回文献证据。"
        )

        if warning not in warnings:
            warnings.append(warning)

    review_result = state.get(
        "literature_review",
        {},
    )

    review_completed = (
        review_result.get("status")
        == "review_completed"
    )

    accepted_assertions = [
        *state.get("accepted_literature_assertion_history", []),
        *state.get("accepted_literature_assertions", []),
    ]
    if not isinstance(accepted_assertions, list):
        accepted_assertions = []
    accepted_element_sets = accepted_five_metal_sets(
        accepted_assertions,
        state.get("task_analysis", {}),
        papers,
    )
    search_round = int(state.get("literature_search_round", 1) or 1)
    max_rounds = int(state.get("literature_max_search_rounds", 3) or 3)
    reached_limit = not accepted_element_sets and search_round >= max_rounds
    evidence_contract = {
        "schema_version": "b-to-c-evidence-v2",
        "status": "evidence_backed_candidate_ready" if accepted_element_sets else "evidence_gap",
        "accepted_assertion_count": len(accepted_assertions),
        # Compatibility alias; this now contains strict five-metal sets only.
        "accepted_explicit_element_sets": accepted_element_sets,
        "accepted_explicit_five_metal_sets": accepted_element_sets,
        "eligible_five_metal_set_count": len(accepted_element_sets),
        "minimum_required_element_count": 5,
        "evidence_backed_candidate_ready": bool(accepted_element_sets),
        "cross_paper_element_union_allowed": False,
        "llm_inferred_elements_allowed": False,
        "exploratory_generation_allowed": False,
        "search_round": search_round,
        "maximum_search_rounds_reached": reached_limit,
        "unresolved_evidence_gaps": [] if accepted_element_sets else [
            "No human-accepted explicit same-paper five-metal HEA composition claim."
        ],
    }

    summary = {
        "rag_used": bool(
            route.get("use_rag")
        ),
        "rag_reason": route.get(
            "rag_reason",
            "",
        ),
        "rag_query": route.get(
            "rag_query",
            "",
        ),
        "evidence_count": len(
            evidence_catalog
        ),
        "evidence_catalog": evidence_catalog,
        "answer": str(
            synthesis.get("answer", "")
        ).strip(),
        "citations": synthesis.get(
            "citations",
            [],
        ),
        "mode": synthesis.get(
            "mode",
            "unknown",
        ),
        "requires_human_review": (
            bool(evidence_catalog)
            and not review_completed
        ),
        "evidence_contract": evidence_contract,
    }

    return {
        "literature_summary": summary,
        "literature_evidence_contract": evidence_contract,
        "literature_evidence_gap": (
            {}
            if accepted_element_sets
            else {
                "status": "literature_evidence_gap",
                "reason": (
                    "maximum_search_rounds_reached"
                    if reached_limit
                    else "eligible_five_metal_set_not_found"
                ),
                "search_rounds_completed": search_round,
                "can_enter_c_stage_with_evidence": False,
            }
        ),
        "warnings": warnings,
        "status": "literature_summarized",
    }


def c_stage_preparation_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Resolve C-stage access and build C1 constraints."""

    task_analysis = state.get(
        "task_analysis",
        {},
    )
    papers = state.get(
        "papers",
        [],
    )
    user_overrides = state.get(
        "candidate_user_overrides",
        {},
    )

    if not isinstance(task_analysis, dict) or not task_analysis:
        return {
            "c_stage_capability": {
                "can_generate_candidates": False,
                "generation_mode": "missing_task_analysis",
                "reason": "Task analysis is required before C stage.",
            },
            "candidate_constraints": {},
            "status": "c_stage_preparation_failed",
            "errors": _append_message(
                state=state,
                node="c_stage_preparation",
                error_type="missing_task_analysis",
                message="C-stage preparation requires task_analysis.",
            ),
        }

    if not isinstance(papers, list):
        papers = []

    if not isinstance(user_overrides, dict):
        return {
            "candidate_constraints": {},
            "status": "c_stage_preparation_failed",
            "errors": _append_message(
                state=state,
                node="c_stage_preparation",
                error_type="invalid_candidate_user_overrides",
                message="candidate_user_overrides must be a dictionary.",
            ),
        }

    try:
        direct_c_stage = state.get("direct_c_stage", {})
        if isinstance(direct_c_stage, dict) and direct_c_stage.get("requested"):
            capability = {
                "schema_version": "c-stage-capability-v1",
                "reaction_id": task_analysis.get("reaction_id", "UNKNOWN"),
                "material_family": "high_entropy_alloy",
                "accepted_evidence_count": 0,
                "evidence_policy": "explicit_user_composition",
                "generation_mode": "direct_explicit_composition",
                "can_generate_candidates": True,
                "scientific_scope": "fcc_high_entropy_metal_alloy",
                "reaction_activity_prediction": False,
                "requires_human_confirmation": True,
                "reason": (
                    "The user explicitly requested FCC modeling of one "
                    "specified five-metal high-entropy alloy."
                ),
                "warnings": [
                    "B-stage literature retrieval was skipped by explicit "
                    "user intent; this composition is an ideal modeling "
                    "hypothesis, not a claim of reaction suitability."
                ],
            }
        else:
            capability = services.c_stage_resolver(
                task_analysis,
                papers,
            )

        warnings = _unique_strings([
            *state.get("warnings", []),
            *capability.get("warnings", []),
        ])

        if not capability.get("can_generate_candidates", False):
            return {
                "c_stage_capability": capability,
                "candidate_constraints": {},
                "candidate_generation": {
                    "status": "candidate_generation_skipped",
                    "candidate_count": 0,
                    "candidates": [],
                    "reason": capability.get("reason", ""),
                },
                "candidate_review": {
                    "status": "candidate_review_skipped",
                    "selected": [],
                    "selected_count": 0,
                    "ready_for_structure_modeling": False,
                    "reason": capability.get("reason", ""),
                },
                "selected_candidates": [],
                "warnings": warnings,
                "status": "c_stage_skipped",
            }

        constraints = services.candidate_constraint_builder.build(
            task_analysis=task_analysis,
            accepted_papers=papers,
            user_overrides=user_overrides,
        )

        warnings = _unique_strings([
            *warnings,
            *constraints.get("warnings", []),
        ])

        return {
            "c_stage_capability": capability,
            "candidate_constraints": constraints,
            "warnings": warnings,
            "status": "candidate_constraints_ready",
        }

    except Exception as error:
        return {
            "candidate_constraints": {},
            "status": "c_stage_preparation_failed",
            "errors": _append_error(
                state=state,
                node="c_stage_preparation",
                error=error,
            ),
        }


def candidate_generation_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Generate C3 candidates and rank them with C2."""

    capability = state.get(
        "c_stage_capability",
        {},
    )
    constraints = state.get(
        "candidate_constraints",
        {},
    )

    if not capability.get("can_generate_candidates", False):
        return {
            "candidate_generation": {
                "status": "candidate_generation_skipped",
                "candidate_count": 0,
                "candidates": [],
                "reason": capability.get(
                    "reason",
                    "C-stage capability does not permit generation.",
                ),
            },
            "status": "candidate_generation_skipped",
        }

    if not isinstance(constraints, dict) or not constraints:
        return {
            "candidate_generation": {
                "status": "candidate_generation_failed",
                "candidate_count": 0,
                "candidates": [],
                "reason": "Candidate constraints are missing.",
            },
            "status": "candidate_generation_failed",
            "errors": _append_message(
                state=state,
                node="candidate_generation",
                error_type="missing_candidate_constraints",
                message="C3 requires candidate_constraints from C1.",
            ),
        }

    try:
        direct_c_stage = state.get("direct_c_stage", {})
        direct_fixed_composition = bool(
            isinstance(direct_c_stage, dict)
            and direct_c_stage.get("requested", False)
        )
        result = services.candidate_generator.generate_and_score(
            constraints=constraints,
            evaluator=services.candidate_evaluator,
            variants_per_combination=(3 if direct_fixed_composition else 1),
            max_candidates=None,
            fixed_composition_variants=direct_fixed_composition,
        )

        if direct_fixed_composition:
            result["candidate_variant_mode"] = (
                "three_deterministic_atomic_arrangements"
            )
            result["display_entity"] = "fixed_composition_fcc_arrangement"
            for index, candidate in enumerate(result.get("candidates", []), 1):
                candidate["candidate_kind"] = "fixed_composition_fcc_arrangement"
                candidate["arrangement_index"] = index

        warnings = _unique_strings([
            *state.get("warnings", []),
            *result.get("warnings", []),
        ])

        return {
            "candidate_generation": {
                **result,
                "status": "candidate_generation_completed",
                "review_limit": CANDIDATE_REVIEW_LIMIT,
                "review_candidate_count": min(
                    len(result.get("candidates", [])),
                    CANDIDATE_REVIEW_LIMIT,
                ),
            },
            "warnings": warnings,
            "status": "candidate_generation_completed",
        }

    except Exception as error:
        return {
            "candidate_generation": {
                "status": "candidate_generation_failed",
                "candidate_count": 0,
                "candidates": [],
                "reason": str(error),
            },
            "status": "candidate_generation_failed",
            "errors": _append_error(
                state=state,
                node="candidate_generation",
                error=error,
            ),
        }


def candidate_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Interrupt LangGraph and wait for candidate selection."""

    generation = state.get(
        "candidate_generation",
        {},
    )
    candidates = generation.get(
        "candidates",
        [],
    )

    if not isinstance(candidates, list):
        candidates = []

    if (
        generation.get("status") != "candidate_generation_completed"
        or not candidates
    ):
        return {
            "candidate_review": {
                "schema_version": "c4.1",
                "status": "candidate_review_skipped",
                "selected_count": 0,
                "selected": [],
                "rejected": [],
                "deferred": [],
                "ready_for_structure_modeling": False,
                "reason": (
                    "No completed candidate generation result is available."
                ),
            },
            "selected_candidates": [],
            "status": "candidate_review_skipped",
        }

    review_candidates = candidates[:CANDIDATE_REVIEW_LIMIT]

    review_request = {
        "type": "candidate_review_required",
        "message": (
            "Please review the highest-ranked material candidates. "
            "Select at most three candidates for later FCC modeling."
        ),
        "task_id": state.get("task_id", ""),
        "question": state.get("question", ""),
        "generation_mode": state.get(
            "c_stage_capability",
            {},
        ).get("generation_mode", "unknown"),
        "scientific_warning": (
            "C2 scores are ranking aids. Selection does not prove "
            "reaction activity or structural stability."
        ),
        "total_candidate_count": len(candidates),
        "displayed_candidate_count": len(review_candidates),
        "max_selected": services.candidate_review_gate.max_selected,
        "instructions": {
            "select": (
                "Permit this candidate to enter later FCC modeling."
            ),
            "reject": (
                "Reject this displayed candidate for the current task."
            ),
            "defer": "Keep this candidate for later review.",
            "default": (
                "Unclassified displayed candidates become deferred."
            ),
        },
        "candidates": [
            _candidate_review_summary(candidate)
            for candidate in review_candidates
        ],
    }

    # GraphInterrupt is LangGraph's normal pause signal.
    decision = interrupt(review_request)

    try:
        review_result = services.candidate_review_gate.review(
            candidates=review_candidates,
            decision=decision,
            total_candidate_count=len(candidates),
        )

        selected = review_result.get("selected", [])

        return {
            "candidate_review": review_result,
            "selected_candidates": selected,
            "status": (
                "candidate_review_completed"
                if selected
                else "candidate_review_completed_no_selection"
            ),
        }

    except Exception as error:
        return {
            "candidate_review": {
                "schema_version": "c4.1",
                "status": "candidate_review_failed",
                "selected_count": 0,
                "selected": [],
                "rejected": [],
                "deferred": review_candidates,
                "ready_for_structure_modeling": False,
                "reason": str(error),
            },
            "selected_candidates": [],
            "status": "candidate_review_failed",
            "errors": _append_error(
                state=state,
                node="candidate_review",
                error=error,
            ),
        }


def c_stage_execution_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Ask how far selected candidates may proceed in C stage."""

    selected = state.get("selected_candidates", [])
    if not isinstance(selected, list) or not selected:
        review = {
            "schema_version": "c4.6",
            "status": "c_stage_execution_review_skipped",
            "mode": "candidate_only",
            "reason": "No candidate was selected for further work.",
            "selected_candidate_count": 0,
        }
        return {
            "c_stage_execution_review": review,
            "c_stage_execution_mode": "candidate_only",
            "status": review["status"],
        }

    request = {
        "type": "c_stage_execution_review_required",
        "schema_version": "c4.6",
        "message": (
            "Candidate selection is complete. Please choose the permitted "
            "boundary for subsequent theoretical work."
        ),
        "message_zh": "候选材料选择已完成，请选择后续理论计算允许执行到哪一步。",
        "selected_candidate_count": len(selected),
        "selected_candidate_ids": [
            str(item.get("candidate_id", "")) for item in selected
        ],
        "recommended_mode": "stability_screening",
        "options": [
            {
                "mode": "candidate_only",
                "label": "Stop after candidate selection",
                "label_zh": "仅保留候选组合并停止",
                "runs": [],
                "explanation": "Keep only the ranked, human-selected compositions.",
                "explanation_zh": "仅保存已排序且经人工选择的候选组成，不继续结构建模。",
            },
            {
                "mode": "fcc_only",
                "label": "Build FCC bulk structures only",
                "label_zh": "仅构建 FCC bulk 结构",
                "runs": ["C5 FCC modeling"],
                "explanation": (
                    "FCC is a common practical starting model for metallic "
                    "high-entropy alloys; it is a modeling assumption, not proof "
                    "that the real material must be single-phase FCC."
                ),
                "explanation_zh": (
                    "FCC 是金属高熵合金常用的实用起始模型，但它属于建模假设，"
                    "不能证明真实材料一定形成单相 FCC。"
                ),
            },
            {
                "mode": "stability_screening",
                "label": "FCC plus property and stability prescreening",
                "label_zh": "FCC 建模 + 形成能与稳定性预筛",
                "runs": ["C5", "C6 formation energy", "C7 delta/Omega"],
                "explanation": (
                    "Recommended: lower-cost theoretical prescreening can reduce "
                    "expensive DFT work. CGCNN-out-of-domain cases remain pending "
                    "and are not submitted to DFT automatically."
                ),
                "explanation_zh": (
                    "推荐：先进行成本较低的理论预筛，可减少昂贵的 DFT 计算。"
                    "CGCNN 分布外结构会保持待定，不会自动提交 DFT。"
                ),
            },
            {
                "mode": "dft_validation",
                "label": "Continue through DFT validation",
                "label_zh": "继续完整 DFT 验证流程",
                "runs": ["C5", "C6", "C7", "C8-C10", "C11"],
                "explanation": (
                    "DFT gives higher-fidelity theoretical validation, but costs "
                    "more compute and may require separate cluster approvals."
                ),
                "explanation_zh": (
                    "DFT 可提供更高保真的理论验证，但计算成本更高，"
                    "并可能需要独立的超算操作审批。"
                ),
            },
        ],
        "submission_safety": (
            "Choosing DFT permits preparation of the DFT workflow; existing C11 "
            "upload and sbatch confirmation gates still apply."
        ),
        "submission_safety_zh": (
            "选择 DFT 只允许准备后续计算流程；C11 的远程上传和 sbatch 提交仍需分别人工确认。"
        ),
    }
    decision = interrupt(request)
    if not isinstance(decision, dict):
        decision = {}
    mode = str(decision.get("mode", "candidate_only")).strip().lower()
    allowed = {
        "candidate_only", "fcc_only", "stability_screening", "dft_validation"
    }
    if mode not in allowed:
        mode = "candidate_only"
    review = {
        "schema_version": "c4.6",
        "status": "c_stage_execution_review_completed",
        "mode": mode,
        "selected_candidate_count": len(selected),
        "note": str(decision.get("note", "")).strip(),
        "explicit_human_confirmation": True,
    }
    return {
        "c_stage_execution_review": review,
        "c_stage_execution_mode": mode,
        "status": review["status"],
    }


def structure_modeling_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Build C5 FCC bulk structures after candidate review."""

    selected = state.get(
        "selected_candidates",
        [],
    )
    review = state.get(
        "candidate_review",
        {},
    )

    if not isinstance(selected, list):
        selected = []

    if (
        not review.get(
            "ready_for_structure_modeling",
            False,
        )
        or not selected
    ):
        result = {
            "schema_version": "c5.0",
            "stage": "c5",
            "status": "structure_modeling_skipped",
            "selected_candidate_count": len(selected),
            "modeled_candidate_count": 0,
            "structure_count": 0,
            "structures": [],
            "failure_count": 0,
            "failures": [],
            "next_stage": "c6_formation_energy",
            "formation_energy_evaluated": False,
            "stability_evaluated": False,
            "slab_generated": False,
        }

        return {
            "structure_modeling": result,
            "bulk_structures": [],
            "status": "structure_modeling_skipped",
        }

    try:
        result = services.structure_modeler.model_candidates(
            selected_candidates=selected,
            structures_per_candidate=1,
            base_seed=42,
        )

        structures = result.get(
            "structures",
            [],
        )

        warnings = list(
            state.get("warnings", [])
        )

        if result.get("failure_count", 0):
            warning = (
                "部分候选在 C5 FCC 建模中失败，"
                "请查看 structure_modeling.failures。"
            )
            if warning not in warnings:
                warnings.append(warning)

        return {
            "structure_modeling": result,
            "bulk_structures": structures,
            "warnings": warnings,
            "status": result.get(
                "status",
                "structure_modeling_failed",
            ),
        }

    except Exception as error:
        return {
            "structure_modeling": {
                "schema_version": "c5.0",
                "stage": "c5",
                "status": "structure_modeling_failed",
                "selected_candidate_count": len(selected),
                "modeled_candidate_count": 0,
                "structure_count": 0,
                "structures": [],
                "failure_count": len(selected),
                "failures": [{
                    "candidate_id": "",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
                "next_stage": "c6_formation_energy",
                "formation_energy_evaluated": False,
                "stability_evaluated": False,
                "slab_generated": False,
            },
            "bulk_structures": [],
            "status": "structure_modeling_failed",
            "errors": _append_error(
                state=state,
                node="structure_modeling",
                error=error,
            ),
        }


def formation_energy_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Run C6 CGCNN prediction or route structures to DFT."""

    bulk_structures = state.get(
        "bulk_structures",
        [],
    )

    if not isinstance(bulk_structures, list):
        bulk_structures = []

    if not bulk_structures:
        result = (
            services.formation_energy_evaluator.evaluate([])
        )

        return {
            "formation_energy_evaluation": result,
            "formation_energy_structures": [],
            "dft_formation_energy_queue": [],
            "status": "formation_energy_skipped",
        }

    try:
        result = (
            services.formation_energy_evaluator.evaluate(
                bulk_structures
            )
        )

        warnings = list(state.get("warnings", []))

        if result.get("waiting_for_dft_count", 0):
            warning = (
                "部分结构超出 CGCNN 训练域，"
                "已进入 DFT 形成能待计算队列。"
            )
            if warning not in warnings:
                warnings.append(warning)

        if result.get("failed_count", 0):
            warning = (
                "部分结构的 CGCNN 形成能预测失败，"
                "不能将其视为 DFT 待计算结果。"
            )
            if warning not in warnings:
                warnings.append(warning)

        return {
            "formation_energy_evaluation": result,
            "formation_energy_structures": (
                result.get("structures", [])
            ),
            "dft_formation_energy_queue": (
                result.get("dft_queue", [])
            ),
            "warnings": warnings,
            "status": result.get(
                "status",
                "formation_energy_failed",
            ),
        }

    except Exception as error:
        return {
            "formation_energy_evaluation": {
                "schema_version": "c6.0",
                "stage": "c6",
                "status": "formation_energy_failed",
                "structure_count": len(bulk_structures),
                "cgcnn_predicted_count": 0,
                "waiting_for_dft_count": 0,
                "failed_count": len(bulk_structures),
                "structures": bulk_structures,
                "dft_queue": [],
                "error_count": 1,
                "errors": [{
                    "structure_id": "",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
                "formation_energy_threshold_applied": False,
                "stability_evaluated": False,
                "slab_generated": False,
                "next_stage": "c7_stability_screening",
            },
            "formation_energy_structures": [],
            "dft_formation_energy_queue": [],
            "status": "formation_energy_failed",
            "errors": _append_error(
                state=state,
                node="formation_energy",
                error=error,
            ),
        }


def formation_energy_source_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Select one task-wide formation-energy source before C7."""

    production_structures = state.get("formation_energy_structures", [])
    if not isinstance(production_structures, list):
        production_structures = []
    predicted = [
        dict(item)
        for item in production_structures
        if isinstance(item, dict)
        and item.get("formation_energy") is not None
    ]
    if not predicted:
        return {
            "formation_energy_source_review": {
                "status": "formation_energy_source_review_skipped",
                "reason": "no_predicted_formation_energy",
            },
            "selected_formation_energy_source": "",
            "selected_formation_energy_structures": production_structures,
            "status": "formation_energy_source_review_skipped",
        }

    task_id = str(state.get("task_id", ""))
    latest = cgcnn_training_manager.latest(task_id)
    temporary_ready = bool(latest and latest.get("status") == "completed")
    decision = interrupt({
        "type": "formation_energy_source_review_required",
        "schema_version": "c6.1",
        "message": (
            "Select exactly one formation-energy source for every candidate. "
            "C7 will not mix values from different models."
        ),
        "recommended_mode": "pretrained",
        "options": [
            {
                "mode": "pretrained",
                "label": "使用生产模型形成能（推荐）",
                "explanation": "使用当前已部署 CGCNN 对全部候选的预测值。",
            },
            {
                "mode": "temporary_trained",
                "label": "使用本任务临时训练模型",
                "explanation": (
                    "仅在 C6 日志面板显示训练完成后选择；"
                    f"当前状态：{latest.get('status') if latest else 'not_started'}。"
                ),
            },
            {
                "mode": "defer",
                "label": "暂缓选择",
                "explanation": "保存当前结果并停止在 C7 之前。",
            },
        ],
        "temporary_model_ready": temporary_ready,
        "temporary_model_run_id": str(latest.get("run_id", "")) if latest else "",
        "structures": [
            {
                "structure_id": str(item.get("structure_id", "")),
                "pretrained_formation_energy_ev_per_atom": item.get("formation_energy"),
                "formation_energy_unit": item.get("formation_energy_unit", "eV/atom"),
            }
            for item in predicted
        ],
        "structure_count": len(predicted),
        "requires_human_confirmation": True,
        "next_stage": "C7 稳定性判据",
    })
    mode = str(decision.get("mode", "")).strip()
    if mode == "defer":
        return {
            "formation_energy_source_review": {
                "status": "formation_energy_source_deferred",
                "selected_source": "defer",
            },
            "selected_formation_energy_source": "defer",
            "selected_formation_energy_structures": [],
            "status": "formation_energy_source_deferred",
        }

    selected = [dict(item) for item in production_structures if isinstance(item, dict)]
    comparison_items: list[dict[str, Any]] = []
    selected_run_id = ""
    if mode == "temporary_trained":
        latest = cgcnn_training_manager.latest(task_id)
        if not latest or latest.get("status") != "completed":
            raise ValueError("临时 CGCNN 尚未训练完成，不能作为 C7 形成能来源。")
        selected_run_id = str(latest["run_id"])
        temporary = {
            str(item.get("structure_id", "")): item
            for item in cgcnn_training_manager.predictions(task_id, selected_run_id)
        }
        for item in selected:
            structure_id = str(item.get("structure_id", ""))
            prediction = temporary.get(structure_id)
            production_value = item.get("formation_energy")
            if prediction is None and production_value is not None:
                raise ValueError(f"临时模型缺少结构 {structure_id} 的形成能预测。")
            temporary_value = prediction.get("formation_energy_ev_per_atom") if prediction else None
            if temporary_value is not None:
                item.update({
                    "pretrained_formation_energy_ev_per_atom": production_value,
                    "temporary_formation_energy_ev_per_atom": temporary_value,
                    "formation_energy": float(temporary_value),
                    "formation_energy_source": "temporary_trained",
                    "temporary_model_run_id": selected_run_id,
                })
            comparison_items.append({
                "structure_id": structure_id,
                "pretrained_formation_energy_ev_per_atom": production_value,
                "temporary_formation_energy_ev_per_atom": temporary_value,
                "prediction_difference_ev_per_atom": (
                    float(temporary_value) - float(production_value)
                    if temporary_value is not None and production_value is not None
                    else None
                ),
            })
    elif mode == "pretrained":
        for item in selected:
            if item.get("formation_energy") is not None:
                item["pretrained_formation_energy_ev_per_atom"] = item["formation_energy"]
                item["formation_energy_source"] = "pretrained"
    else:
        raise ValueError(f"Unknown formation-energy source: {mode}")

    return {
        "formation_energy_comparison": {
            "schema_version": "c6.1",
            "status": "formation_energy_comparison_completed",
            "selected_source": mode,
            "temporary_model_run_id": selected_run_id,
            "items": comparison_items,
        },
        "formation_energy_source_review": {
            "status": "formation_energy_source_selected",
            "selected_source": mode,
            "temporary_model_run_id": selected_run_id,
        },
        "selected_formation_energy_source": mode,
        "selected_formation_energy_structures": selected,
        "formation_energy_structures": selected,
        "status": "formation_energy_source_selected",
    }

def bulk_dft_input_preview_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Create C6D bulk formation-energy VASP previews."""

    try:
        result = services.bulk_dft_input_bundle_service.preview(
            state.get("dft_formation_energy_queue", []),
            str(state.get("task_id", "")),
        )
        return {
            "bulk_dft_input_preview": result,
            "status": result["status"],
        }
    except Exception as error:
        return {
            "bulk_dft_input_preview": {
                "schema_version": "c6d.0",
                "status": "bulk_dft_input_preview_failed",
                "bundles": [],
                "reason": str(error),
            },
            "status": "bulk_dft_input_preview_failed",
            "errors": _append_error(
                state,
                "bulk_dft_input_preview",
                error,
            ),
        }


def bulk_dft_input_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Pause for review of all five C6D bulk VASP files."""

    preview = state.get("bulk_dft_input_preview", {})
    bundles = preview.get("bundles", [])
    if not isinstance(bundles, list):
        bundles = []

    if not bundles:
        return {
            "bulk_dft_input_review": {
                "action": "finalize",
                "approve": [],
                "reject": [],
                "defer": [],
                "file_confirmations": {},
            },
            "status": "bulk_dft_input_review_skipped",
        }

    decision = interrupt({
        "type": "bulk_dft_input_review_required",
        "stage_label": "C6D",
        "message": (
            "Review the five bulk formation-energy VASP files."
        ),
        "bundles": bundles,
        "revision_count": state.get(
            "bulk_dft_revision_count", 0
        ),
        "revision_validation": state.get(
            "bulk_dft_revision_validation", {}
        ),
    })
    return {
        "bulk_dft_input_review": decision,
        "bulk_dft_revision_request": decision.get(
            "revision_requests", {}
        ),
        "status": "bulk_dft_input_review_completed",
    }


def bulk_dft_revision_plan_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Translate a C6D natural-language revision into JSON."""

    try:
        result = (
            services.bulk_dft_input_revision_service.parse_requests(
                state.get("bulk_dft_revision_request", {}),
                state.get("bulk_dft_input_preview", {}),
            )
        )
        return {
            "bulk_dft_revision_plan": result,
            "bulk_dft_revision_validation": {},
            "status": "bulk_dft_revision_plan_ready",
        }
    except Exception as error:
        return {
            "bulk_dft_revision_plan": {},
            "bulk_dft_revision_validation": {
                "status": "bulk_dft_revision_rejected",
                "reason": str(error),
                "poscar_unchanged": True,
            },
            "status": "bulk_dft_revision_rejected",
            "errors": _append_error(
                state,
                "bulk_dft_revision_plan",
                error,
            ),
        }


def bulk_dft_revision_apply_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Apply a validated C6D revision while preserving POSCAR."""

    plan = state.get("bulk_dft_revision_plan", {})
    if not plan:
        return {"status": "bulk_dft_revision_rejected"}

    try:
        result = services.bulk_dft_input_revision_service.apply(
            state.get("bulk_dft_input_preview", {}),
            plan,
            int(state.get("bulk_dft_revision_count", 0)),
            state.get("bulk_dft_revision_history", []),
        )
        return {
            "bulk_dft_input_preview": result["preview"],
            "bulk_dft_revision_validation": result["validation"],
            "bulk_dft_revision_history": result["history"],
            "bulk_dft_revision_count": result["revision_count"],
            "bulk_dft_input_review": {},
            "status": "bulk_dft_revision_accepted",
        }
    except Exception as error:
        return {
            "bulk_dft_revision_validation": {
                "status": "bulk_dft_revision_rejected",
                "reason": str(error),
                "poscar_unchanged": True,
            },
            "status": "bulk_dft_revision_rejected",
            "errors": _append_error(
                state,
                "bulk_dft_revision_apply",
                error,
            ),
        }


def bulk_dft_input_finalize_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Atomically create reviewed C6D bulk input directories."""

    try:
        result = services.bulk_dft_input_bundle_service.finalize(
            state.get("bulk_dft_input_preview", {}),
            state.get("bulk_dft_input_review", {}),
        )
        if result.get("status") == "dft_input_preparation_completed":
            result["status"] = (
                "bulk_dft_input_preparation_completed"
            )
        result["schema_version"] = "c6d.0"
        result["stage"] = "c6d_finalize"
        result["next_stage"] = "c11_bulk_cluster_preflight"
        return {
            "bulk_dft_input_preparation": result,
            "bulk_dft_jobs": result.get("jobs", []),
            "status": result["status"],
        }
    except Exception as error:
        return {
            "bulk_dft_input_preparation": {
                "schema_version": "c6d.0",
                "status": "bulk_dft_input_preparation_failed",
                "jobs": [],
                "failures": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
            },
            "bulk_dft_jobs": [],
            "status": "bulk_dft_input_preparation_failed",
            "errors": _append_error(
                state,
                "bulk_dft_input_finalize",
                error,
            ),
        }


def dft_execution_options_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Pause before cluster checks to select the DFT energy mode."""

    bulk_jobs = state.get("bulk_dft_jobs", [])
    slab_jobs = state.get("dft_jobs", [])

    if bulk_jobs:
        jobs = bulk_jobs
        source = "c6d_bulk_formation"
    elif slab_jobs:
        jobs = slab_jobs
        source = "c10_slab"
    else:
        return {
            "dft_execution_options": {
                "action": "defer",
                "mode": None,
                "status": "dft_execution_options_skipped",
            },
            "dft_preflight_jobs": [],
            "dft_job_source": "",
            "status": "dft_execution_options_skipped",
        }

    decision = interrupt({
        "type": "dft_execution_options_required",
        "message": "请选择本次 DFT 计算精度。",
        "job_source": source,
        "job_count": len(jobs),
        "jobs": [{
            "job_id": job.get("job_id"),
            "structure_id": job.get("structure_id"),
            "slab_id": job.get("slab_id"),
            "job_dir": job.get("job_dir"),
            "element_order": job.get("element_order", []),
        } for job in jobs],
        "choices": [
            {
                "value": "relax_only",
                "label": "仅弛豫",
                "description": "使用弛豫 OUTCAR 最终能量。",
            },
            {
                "value": "relax_then_static",
                "label": "弛豫加静态单点",
                "description": "弛豫完成后追加静态能计算。",
            },
            {
                "value": "defer",
                "label": "暂不提交",
                "description": "保留五文件并结束当前流程。",
            },
        ],
    })

    if not isinstance(decision, dict):
        raise TypeError("DFT execution decision must be a dictionary")

    mode = str(decision.get("mode", "")).strip()
    if mode not in {
        "relax_only",
        "relax_then_static",
        "defer",
    }:
        raise ValueError("Unsupported DFT execution mode")

    action = "defer" if mode == "defer" else "continue"

    return {
        "dft_execution_options": {
            "schema_version": "c11.1",
            "status": "dft_execution_options_selected",
            "action": action,
            "mode": mode,
            "energy_source": (
                "static"
                if mode == "relax_then_static"
                else "relax"
                if mode == "relax_only"
                else None
            ),
            "requires_consistent_energy_source": True,
            "submission_performed": False,
        },
        "dft_preflight_jobs": jobs,
        "dft_job_source": source,
        "status": "dft_execution_options_selected",
    }


def adsorption_dft_execution_options_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Select relaxation or defer for C12.6 adsorption jobs."""

    jobs = state.get("adsorption_dft_jobs", [])
    if not isinstance(jobs, list):
        jobs = []

    if not jobs:
        return {
            "dft_execution_options": {
                "schema_version": "c12.6",
                "status": (
                    "adsorption_execution_options_skipped"
                ),
                "action": "defer",
                "mode": None,
                "submission_performed": False,
            },
            "dft_preflight_jobs": [],
            "dft_job_source": "",
            "status": "adsorption_execution_options_skipped",
        }

    decision = interrupt({
        "type": "adsorption_dft_execution_required",
        "message": (
            "C12.6 supports adsorption relaxation only. "
            "Static calculations are disabled."
        ),
        "job_source": "c12_5_adsorption",
        "job_count": len(jobs),
        "jobs": [{
            "job_id": job.get("job_id"),
            "adsorption_structure_id": job.get(
                "adsorption_structure_id"
            ),
            "adsorbate": job.get("adsorbate"),
            "site_id": job.get("site_id"),
            "job_dir": job.get("job_dir"),
        } for job in jobs],
        "choices": [
            {
                "value": "relax_only",
                "label": "Adsorption relaxation",
            },
            {
                "value": "defer",
                "label": "Do not submit now",
            },
        ],
    })

    if not isinstance(decision, dict):
        raise TypeError(
            "Adsorption execution decision must be a dictionary"
        )

    mode = str(decision.get("mode", "defer")).strip()
    if mode not in {"relax_only", "defer"}:
        raise ValueError(
            "C12.6 only supports relax_only or defer"
        )

    continued = mode == "relax_only"
    options = {
        "schema_version": "c12.6",
        "stage": "adsorption_execution_options",
        "status": "adsorption_execution_options_selected",
        "action": "continue" if continued else "defer",
        "mode": mode,
        "energy_source": "relax" if continued else None,
        "requires_consistent_energy_source": True,
        "submission_performed": False,
    }

    return {
        "dft_execution_options": options,
        "adsorption_execution_status": options,
        "dft_preflight_jobs": jobs if continued else [],
        "dft_job_source": (
            "c12_5_adsorption" if continued else ""
        ),
        "status": "adsorption_execution_options_selected",
    }


def dft_local_preflight_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Run C11.2 local checks without cluster access."""

    jobs = state.get("dft_preflight_jobs", [])
    source = str(state.get("dft_job_source", ""))

    if source == "c6d_bulk_formation":
        preview = state.get(
            "bulk_dft_input_preview",
            {},
        )
    elif source == "c10_slab":
        preview = state.get(
            "dft_input_preview",
            {},
        )
    elif source == "c12_5_adsorption":
        preview = state.get(
            "adsorption_dft_input_preview",
            {},
        )
    else:
        preview = {}

    try:
        result = (
            services.dft_local_preflight_service.inspect(
                jobs=jobs,
                preview=preview,
                job_source=source,
            )
        )

        warnings = list(state.get("warnings", []))

        if result.get("failed_count", 0):
            warning = (
                "部分 DFT 计算目录未通过 C11.2 "
                "本地五文件预检查，禁止进入超算检查。"
            )
            if warning not in warnings:
                warnings.append(warning)

        return {
            "dft_local_preflight": result,
            "dft_local_preflight_jobs": (
                result.get("eligible_jobs", [])
            ),
            "warnings": warnings,
            "status": result.get(
                "status",
                "dft_local_preflight_failed",
            ),
        }

    except Exception as error:
        return {
            "dft_local_preflight": {
                "schema_version": "c11.2",
                "stage": "dft_local_preflight",
                "status": "dft_local_preflight_failed",
                "job_count": len(jobs),
                "passed_count": 0,
                "failed_count": len(jobs),
                "jobs": [],
                "eligible_jobs": [],
                "reason": str(error),
                "submission_performed": False,
            },
            "dft_local_preflight_jobs": [],
            "status": "dft_local_preflight_failed",
            "errors": _append_error(
                state,
                "dft_local_preflight",
                error,
            ),
        }


def cluster_readonly_preflight_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Run C11.3 remote read-only environment checks."""

    jobs = state.get(
        "dft_local_preflight_jobs",
        [],
    )

    if not isinstance(jobs, list):
        jobs = []

    try:
        result = (
            services
            .cluster_readonly_preflight_service
            .inspect(jobs=jobs)
        )

        warnings = list(
            state.get("warnings", [])
        )

        if result.get("status") not in {
            "cluster_readonly_preflight_passed",
            "cluster_readonly_preflight_skipped",
        }:
            warning = (
                "C11.3 cluster read-only preflight "
                "did not pass. Upload and submission "
                "remain blocked."
            )

            if warning not in warnings:
                warnings.append(warning)

        return {
            "cluster_readonly_preflight": result,
            "cluster_preflight_jobs": result.get(
                "eligible_jobs",
                [],
            ),
            "warnings": warnings,
            "status": result.get(
                "status",
                "cluster_readonly_preflight_failed",
            ),
        }

    except Exception as error:
        return {
            "cluster_readonly_preflight": {
                "schema_version": "c11.3",
                "stage": "cluster_readonly_preflight",
                "status": (
                    "cluster_readonly_preflight_failed"
                ),
                "job_count": len(jobs),
                "passed_count": 0,
                "failed_count": len(jobs),
                "jobs": jobs,
                "eligible_jobs": [],
                "checks": [],
                "errors": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
                "upload_performed": False,
                "remote_write_performed": False,
                "submission_performed": False,
            },
            "cluster_preflight_jobs": [],
            "status": (
                "cluster_readonly_preflight_failed"
            ),
            "errors": _append_error(
                state,
                "cluster_readonly_preflight",
                error,
            ),
        }


def remote_execution_plan_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Plan C11.4 remote paths without remote writes."""

    jobs = state.get(
        "cluster_preflight_jobs",
        [],
    )

    if not isinstance(jobs, list):
        jobs = []

    try:
        result = (
            services.remote_execution_plan_service.plan(
                jobs=jobs,
                task_id=str(
                    state.get("task_id", "")
                ),
                job_source=str(
                    state.get("dft_job_source", "")
                ),
            )
        )

        return {
            "remote_execution_plan": result,
            "status": result.get(
                "status",
                "remote_execution_plan_failed",
            ),
        }

    except Exception as error:
        return {
            "remote_execution_plan": {
                "schema_version": "c11.4.1",
                "stage": "remote_execution_plan",
                "status": "remote_execution_plan_failed",
                "job_count": len(jobs),
                "jobs": [],
                "remote_write_performed": False,
                "upload_performed": False,
                "submission_performed": False,
                "errors": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
            },
            "status": "remote_execution_plan_failed",
            "errors": _append_error(
                state,
                "remote_execution_plan",
                error,
            ),
        }


def remote_upload_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Require explicit approval before any remote write."""

    plan = state.get(
        "remote_execution_plan",
        {},
    )

    if (
        plan.get("status")
        != "remote_execution_plan_ready"
    ):
        return {
            "remote_upload_review": {
                "status": "remote_upload_review_skipped",
                "approved_job_ids": [],
            },
            "status": "remote_upload_review_skipped",
        }

    request = {
        "type": "remote_upload_review_required",
        "message": (
            "Review remote paths, five-file hashes, "
            "and approve upload explicitly."
        ),
        "task_id": plan.get("task_id"),
        "plan_digest": plan.get("plan_digest"),
        "remote_batch_directory": plan.get(
            "remote_batch_directory"
        ),
        "jobs": plan.get("jobs", []),
        "confirmation_phrase": (
            f"UPLOAD {plan.get('task_id', '')}"
        ),
    }

    decision = interrupt(request)

    if not isinstance(decision, dict):
        raise TypeError(
            "Remote upload decision must be a dictionary"
        )

    action = str(
        decision.get("action", "defer")
    ).strip()

    if action not in {
        "approve_upload",
        "defer",
    }:
        raise ValueError(
            "Unsupported remote upload action"
        )

    approved_job_ids = decision.get(
        "approved_job_ids",
        [],
    )

    if not isinstance(approved_job_ids, list):
        raise TypeError(
            "approved_job_ids must be a list"
        )

    review = {
        "schema_version": "c11.4.2",
        "stage": "remote_upload_review",
        "status": (
            "remote_upload_approved"
            if action == "approve_upload"
            else "remote_upload_deferred"
        ),
        "action": action,
        "plan_digest": decision.get(
            "plan_digest",
            "",
        ),
        "approved_job_ids": approved_job_ids,
        "confirmation_text": decision.get(
            "confirmation_text",
            "",
        ),
        "note": decision.get("note", ""),
        "remote_write_performed": False,
        "upload_performed": False,
        "submission_performed": False,
    }

    return {
        "remote_upload_review": review,
        "status": review["status"],
    }


def remote_upload_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Upload approved files and verify remote hashes."""

    plan = state.get(
        "remote_execution_plan",
        {},
    )
    review = state.get(
        "remote_upload_review",
        {},
    )

    try:
        result = services.remote_upload_service.upload(
            plan=plan,
            review=review,
        )

        return {
            "remote_upload_result": result,
            "remote_verified_jobs": result.get(
                "verified_jobs",
                [],
            ),
            "status": result.get(
                "status",
                "remote_upload_failed",
            ),
        }

    except Exception as error:
        return {
            "remote_upload_result": {
                "schema_version": "c11.4.2",
                "stage": "remote_upload",
                "status": "remote_upload_failed",
                "jobs": [],
                "verified_jobs": [],
                "errors": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
                "remote_write_performed": False,
                "upload_performed": False,
                "submission_performed": False,
            },
            "remote_verified_jobs": [],
            "status": "remote_upload_failed",
            "errors": _append_error(
                state,
                "remote_upload",
                error,
            ),
        }


def remote_submission_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Require explicit approval before sbatch."""

    upload_result = state.get(
        "remote_upload_result",
        {},
    )
    verified_jobs = state.get(
        "remote_verified_jobs",
        [],
    )
    plan = state.get(
        "remote_execution_plan",
        {},
    )

    if (
        upload_result.get("status")
        != "remote_upload_verified"
        or not isinstance(verified_jobs, list)
        or not verified_jobs
    ):
        return {
            "remote_submission_review": {
                "schema_version": "c11.4.3",
                "stage": "remote_submission_review",
                "status": (
                    "remote_submission_review_skipped"
                ),
                "approved_job_ids": [],
                "submission_performed": False,
            },
            "status": (
                "remote_submission_review_skipped"
            ),
        }

    request = {
        "type": "remote_submission_review_required",
        "message": (
            "The uploaded VASP files passed remote "
            "SHA-256 verification. Review each job "
            "before allowing sbatch."
        ),
        "task_id": plan.get("task_id"),
        "plan_digest": plan.get("plan_digest"),
        "confirmation_phrase": (
            f"SUBMIT {plan.get('task_id', '')}"
        ),
        "jobs": [{
            "job_id": job.get("job_id"),
            "remote_job_directory": job.get(
                "remote_job_directory"
            ),
            "remote_hash_verified": job.get(
                "remote_hash_verified",
                False,
            ),
            "slurm_script": "vasp.slurm",
        } for job in verified_jobs],
    }

    decision = interrupt(request)

    if not isinstance(decision, dict):
        raise TypeError(
            "Remote submission decision must be a dictionary"
        )

    action = str(
        decision.get("action", "defer")
    ).strip()

    if action not in {
        "approve_submission",
        "defer",
    }:
        raise ValueError(
            "Unsupported remote submission action"
        )

    approved_job_ids = decision.get(
        "approved_job_ids",
        [],
    )

    if not isinstance(approved_job_ids, list):
        raise TypeError(
            "approved_job_ids must be a list"
        )

    review = {
        "schema_version": "c11.4.3",
        "stage": "remote_submission_review",
        "status": (
            "remote_submission_approved"
            if action == "approve_submission"
            else "remote_submission_deferred"
        ),
        "action": action,
        "plan_digest": decision.get(
            "plan_digest",
            "",
        ),
        "approved_job_ids": approved_job_ids,
        "confirmation_text": decision.get(
            "confirmation_text",
            "",
        ),
        "note": decision.get("note", ""),
        "submission_performed": False,
    }

    return {
        "remote_submission_review": review,
        "status": review["status"],
    }


def remote_submission_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Recheck remote files and submit approved jobs."""

    plan = state.get(
        "remote_execution_plan",
        {},
    )
    verified_jobs = state.get(
        "remote_verified_jobs",
        [],
    )
    review = state.get(
        "remote_submission_review",
        {},
    )

    if not isinstance(verified_jobs, list):
        verified_jobs = []

    try:
        result = (
            services.remote_submission_service.submit(
                plan=plan,
                verified_jobs=verified_jobs,
                review=review,
            )
        )

        return {
            "remote_submission_result": result,
            "submitted_dft_jobs": result.get(
                "submitted_jobs",
                [],
            ),
            "status": result.get(
                "status",
                "remote_submission_failed",
            ),
        }

    except Exception as error:
        return {
            "remote_submission_result": {
                "schema_version": "c11.4.3",
                "stage": "remote_submission",
                "status": "remote_submission_failed",
                "jobs": [],
                "submitted_jobs": [],
                "slurm_job_ids": [],
                "submission_performed": False,
                "automatic_retry_allowed": False,
                "errors": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
            },
            "submitted_dft_jobs": [],
            "status": "remote_submission_failed",
            "errors": _append_error(
                state,
                "remote_submission",
                error,
            ),
        }


def adsorption_reaction_planning_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Create the deterministic C12.1 adsorption plan."""

    task_analysis = state.get(
        "task_analysis",
        {},
    )
    reaction_profile = state.get(
        "reaction_profile",
        {},
    )
    overrides = state.get(
        "adsorption_user_overrides",
        {},
    )
    literature_suggestions = state.get(
        "adsorption_literature_suggestions",
        [],
    )

    try:
        result = (
            services.adsorption_reaction_planner.plan(
                task_analysis=task_analysis,
                reaction_profile=reaction_profile,
                user_overrides=overrides,
                literature_suggestions=(
                    literature_suggestions
                ),
            )
        )

        warnings = list(
            state.get("warnings", [])
        )

        for warning in result.get(
            "warnings",
            [],
        ):
            if warning not in warnings:
                warnings.append(warning)

        return {
            "adsorption_reaction_plan": result,
            "planned_adsorbates": [],
            "warnings": warnings,
            "status": result.get(
                "status",
                "adsorption_reaction_planning_failed",
            ),
        }

    except Exception as error:
        return {
            "adsorption_reaction_plan": {
                "schema_version": "c12.1",
                "stage": "c12.1",
                "status": (
                    "adsorption_reaction_planning_failed"
                ),
                "formal_adsorbates": [],
                "ready_for_site_generation": False,
                "reason": str(error),
                "next_stage": (
                    "human_reaction_plan_review"
                ),
            },
            "planned_adsorbates": [],
            "status": (
                "adsorption_reaction_planning_failed"
            ),
            "errors": _append_error(
                state=state,
                node=(
                    "adsorption_reaction_planning"
                ),
                error=error,
            ),
        }


def adsorption_site_generation_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Enumerate C12.2 sites from relaxed clean-slab CONTCAR files."""

    slabs = state.get("adsorption_source_slabs", [])
    reaction_plan = state.get("adsorption_reaction_plan", {})
    if not isinstance(slabs, list):
        slabs = []
    try:
        result = services.adsorption_site_generation_service.generate(
            slabs=slabs,
            reaction_plan=reaction_plan,
        )
        warnings = list(state.get("warnings", []))
        for warning in result.get("warnings", []):
            if warning not in warnings:
                warnings.append(warning)
        return {
            "adsorption_site_generation": result,
            "adsorption_sites": result.get("sites", []),
            "warnings": warnings,
            "status": result.get(
                "status", "adsorption_site_generation_failed"
            ),
        }
    except Exception as error:
        return {
            "adsorption_site_generation": {
                "schema_version": "c12.2",
                "stage": "c12.2",
                "status": "adsorption_site_generation_failed",
                "input_slab_count": len(slabs),
                "processed_slab_count": 0,
                "failed_slab_count": len(slabs),
                "site_count": 0,
                "slabs": [],
                "sites": [],
                "errors": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
                "required_structure_source": "relaxed_clean_slab_contcar",
                "original_slab_fallback_allowed": False,
                "structure_modified": False,
                "adsorbate_placed": False,
                "adsorbate_instance_limit": 1,
                "coadsorption_allowed": False,
                "remote_operation_performed": False,
                "next_stage": "human_adsorption_input_review",
            },
            "adsorption_sites": [],
            "status": "adsorption_site_generation_failed",
            "errors": _append_error(
                state=state,
                node="adsorption_site_generation",
                error=error,
            ),
        }


def adsorbate_structure_generation_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Build C12.3 single-adsorbate structures."""

    sites = state.get(
        "adsorption_sites",
        [],
    )
    reaction_plan = state.get(
        "adsorption_reaction_plan",
        {},
    )

    if not isinstance(sites, list):
        sites = []

    try:
        result = (
            services
            .adsorbate_structure_builder
            .build(
                task_id=str(
                    state.get("task_id", "")
                ),
                sites=sites,
                reaction_plan=reaction_plan,
            )
        )

        return {
            "adsorbate_structure_generation": (
                result
            ),
            "adsorption_structures": result.get(
                "structures",
                [],
            ),
            "status": result.get(
                "status",
                "adsorbate_structure_generation_failed",
            ),
        }

    except Exception as error:
        return {
            "adsorbate_structure_generation": {
                "schema_version": "c12.3",
                "stage": "c12.3",
                "status": (
                    "adsorbate_structure_generation_failed"
                ),
                "input_site_count": len(sites),
                "generated_structure_count": 0,
                "failure_count": len(sites),
                "structures": [],
                "failures": [{
                    "error_type": (
                        type(error).__name__
                    ),
                    "message": str(error),
                }],
                "adsorbate_instance_limit": 1,
                "coadsorption_allowed": False,
                "single_adsorbate_per_structure": True,
                "remote_operation_performed": False,
                "next_stage": (
                    "human_adsorption_input_review"
                ),
            },
            "adsorption_structures": [],
            "status": (
                "adsorbate_structure_generation_failed"
            ),
            "errors": _append_error(
                state=state,
                node=(
                    "adsorbate_structure_generation"
                ),
                error=error,
            ),
        }


def adsorption_structure_quality_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Run C12.4 initial-geometry checks."""

    structures = state.get(
        "adsorption_structures",
        [],
    )

    if not isinstance(structures, list):
        structures = []

    try:
        result = (
            services
            .adsorption_structure_quality_inspector
            .inspect(structures)
        )

        return {
            "adsorption_structure_quality": result,
            "quality_passed_adsorption_structures": (
                result.get(
                    "quality_passed_structures",
                    [],
                )
            ),
            "status": result.get(
                "status",
                "adsorption_quality_failed",
            ),
        }

    except Exception as error:
        return {
            "adsorption_structure_quality": {
                "schema_version": "c12.4",
                "stage": "c12.4_quality",
                "status": (
                    "adsorption_quality_failed"
                ),
                "reports": [],
                "quality_passed_structures": [],
                "errors": [{
                    "error_type": (
                        type(error).__name__
                    ),
                    "message": str(error),
                }],
            },
            "quality_passed_adsorption_structures": [],
            "status": "adsorption_quality_failed",
            "errors": _append_error(
                state=state,
                node=(
                    "adsorption_structure_quality"
                ),
                error=error,
            ),
        }


def adsorption_structure_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Pause for C12.4 adsorption review."""

    structures = state.get(
        "quality_passed_adsorption_structures",
        [],
    )

    if not isinstance(structures, list):
        structures = []

    if not structures:
        return {
            "adsorption_structure_review": {
                "schema_version": "c12.4",
                "stage": "c12.4_review",
                "status": (
                    "adsorption_structure_review_skipped"
                ),
                "approved": [],
                "rejected": [],
                "deferred": [],
            },
            "adsorption_dft_approved_structures": [],
            "status": (
                "adsorption_structure_review_skipped"
            ),
        }

    decision = interrupt({
        "type": (
            "adsorption_structure_review_required"
        ),
        "message": (
            "Review single-adsorbate structures "
            "before VASP input preparation."
        ),
        "maximum_approved": 15,
        "structures": [{
            "adsorption_structure_id": item.get(
                "adsorption_structure_id"
            ),
            "slab_id": item.get("slab_id"),
            "adsorbate": item.get(
                "adsorbate"
            ),
            "site_id": item.get("site_id"),
            "site_type": item.get(
                "site_type"
            ),
            "chemistry_signature": item.get(
                "chemistry_signature"
            ),
            "minimum_adsorbate_slab_distance_angstrom": (
                item.get(
                    "minimum_adsorbate_slab_distance_angstrom"
                )
            ),
            "remaining_top_vacuum_angstrom": (
                item.get(
                    "remaining_top_vacuum_angstrom"
                )
            ),
            "poscar_path": item.get(
                "poscar_path"
            ),
            "failed_checks": item.get(
                "failed_checks",
                [],
            ),
        } for item in structures],
    })

    try:
        result = (
            services
            .adsorption_structure_review_gate
            .review(
                structures,
                decision,
            )
        )

        return {
            "adsorption_structure_review": result,
            "adsorption_dft_approved_structures": (
                result.get("approved", [])
            ),
            "status": (
                "adsorption_structure_review_completed"
            ),
        }

    except Exception as error:
        return {
            "adsorption_structure_review": {
                "schema_version": "c12.4",
                "stage": "c12.4_review",
                "status": (
                    "adsorption_structure_review_failed"
                ),
                "approved": [],
                "reason": str(error),
            },
            "adsorption_dft_approved_structures": [],
            "status": (
                "adsorption_structure_review_failed"
            ),
            "errors": _append_error(
                state=state,
                node=(
                    "adsorption_structure_review"
                ),
                error=error,
            ),
        }


def adsorption_dft_preview_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Create C12.5 five-file previews for approved structures."""

    structures = state.get(
        "adsorption_dft_approved_structures",
        [],
    )
    if not isinstance(structures, list):
        structures = []

    try:
        result = (
            services
            .adsorption_dft_input_bundle_service
            .preview(
                approved_structures=structures,
                task_id=str(state.get("task_id", "")),
            )
        )
        return {
            "adsorption_dft_input_preview": result,
            "status": result.get(
                "status",
                "adsorption_dft_preview_failed",
            ),
        }
    except Exception as error:
        return {
            "adsorption_dft_input_preview": {
                "schema_version": "c12.5",
                "stage": "c12.5_preview",
                "status": "adsorption_dft_preview_failed",
                "bundle_count": 0,
                "bundles": [],
                "formal_files_written": False,
                "reason": str(error),
            },
            "status": "adsorption_dft_preview_failed",
            "errors": _append_error(
                state=state,
                node="adsorption_dft_preview",
                error=error,
            ),
        }


def adsorption_dft_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Pause C12.5 for five-file review or revision."""

    preview = state.get(
        "adsorption_dft_input_preview",
        {},
    )
    bundles = preview.get("bundles", [])
    if not isinstance(bundles, list):
        bundles = []

    if not bundles:
        return {
            "adsorption_dft_input_review": {
                "schema_version": "c12.5",
                "status": "adsorption_dft_review_skipped",
                "action": "finalize",
                "approve": [],
                "reject": [],
                "defer": [],
                "file_confirmations": {},
            },
            "status": "adsorption_dft_review_skipped",
        }

    decision = interrupt({
        "type": "adsorption_dft_input_review_required",
        "stage_label": "C12.5",
        "message": (
            "Review all five VASP inputs for each "
            "single-adsorbate structure."
        ),
        "bundles": bundles,
        "revision_count": state.get(
            "adsorption_dft_revision_count",
            0,
        ),
        "revision_validation": state.get(
            "adsorption_dft_revision_validation",
            {},
        ),
        "poscar_immutable": True,
        "submission_performed": False,
    })

    if not isinstance(decision, dict):
        raise TypeError(
            "C12.5 review decision must be a dictionary"
        )

    return {
        "adsorption_dft_input_review": decision,
        "adsorption_dft_revision_request": decision.get(
            "revision_requests",
            {},
        ),
        "status": "adsorption_dft_review_completed",
    }


def adsorption_dft_revision_plan_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Translate C12.5 natural-language revisions into JSON."""

    try:
        result = (
            services
            .adsorption_dft_input_revision_service
            .parse_requests(
                revision_requests=state.get(
                    "adsorption_dft_revision_request",
                    {},
                ),
                preview=state.get(
                    "adsorption_dft_input_preview",
                    {},
                ),
            )
        )
        return {
            "adsorption_dft_revision_plan": result,
            "adsorption_dft_revision_validation": {},
            "status": "adsorption_dft_revision_plan_ready",
        }
    except Exception as error:
        return {
            "adsorption_dft_revision_plan": {},
            "adsorption_dft_revision_validation": {
                "schema_version": "c12.5-revision-v1",
                "status": "adsorption_dft_revision_rejected",
                "reason": str(error),
                "poscar_unchanged": True,
            },
            "status": "adsorption_dft_revision_rejected",
            "errors": _append_error(
                state=state,
                node="adsorption_dft_revision_plan",
                error=error,
            ),
        }


def adsorption_dft_revision_apply_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Apply a validated C12.5 revision without changing POSCAR."""

    plan = state.get(
        "adsorption_dft_revision_plan",
        {},
    )
    if not plan:
        return {
            "status": "adsorption_dft_revision_rejected",
        }

    try:
        result = (
            services
            .adsorption_dft_input_revision_service
            .apply(
                preview=state.get(
                    "adsorption_dft_input_preview",
                    {},
                ),
                plan=plan,
                revision_count=int(state.get(
                    "adsorption_dft_revision_count",
                    0,
                )),
                history=state.get(
                    "adsorption_dft_revision_history",
                    [],
                ),
            )
        )
        return {
            "adsorption_dft_input_preview": result[
                "preview"
            ],
            "adsorption_dft_revision_validation": result[
                "validation"
            ],
            "adsorption_dft_revision_history": result[
                "history"
            ],
            "adsorption_dft_revision_count": result[
                "revision_count"
            ],
            "adsorption_dft_input_review": {},
            "status": "adsorption_dft_revision_accepted",
        }
    except Exception as error:
        return {
            "adsorption_dft_revision_validation": {
                "schema_version": "c12.5-revision-v1",
                "status": "adsorption_dft_revision_rejected",
                "reason": str(error),
                "poscar_unchanged": True,
            },
            "status": "adsorption_dft_revision_rejected",
            "errors": _append_error(
                state=state,
                node="adsorption_dft_revision_apply",
                error=error,
            ),
        }


def adsorption_dft_finalize_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Atomically create reviewed C12.5 calculation directories."""

    try:
        result = (
            services
            .adsorption_dft_input_bundle_service
            .finalize(
                preview=state.get(
                    "adsorption_dft_input_preview",
                    {},
                ),
                review=state.get(
                    "adsorption_dft_input_review",
                    {},
                ),
            )
        )
        return {
            "adsorption_dft_input_preparation": result,
            "adsorption_dft_jobs": result.get(
                "jobs",
                [],
            ),
            "status": result.get(
                "status",
                "adsorption_dft_input_preparation_failed",
            ),
        }
    except Exception as error:
        return {
            "adsorption_dft_input_preparation": {
                "schema_version": "c12.5",
                "stage": "c12.5_finalize",
                "status": (
                    "adsorption_dft_input_preparation_failed"
                ),
                "jobs": [],
                "failures": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
                "submission_performed": False,
            },
            "adsorption_dft_jobs": [],
            "status": (
                "adsorption_dft_input_preparation_failed"
            ),
            "errors": _append_error(
                state=state,
                node="adsorption_dft_finalize",
                error=error,
            ),
        }


def adsorption_energy_calculation_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Calculate simplified C12.7 adsorption energies."""

    results = state.get("adsorption_parsed_results", [])
    if not isinstance(results, list):
        results = []

    try:
        calculation = (
            services.adsorption_energy_calculator.calculate(
                adsorption_results=results,
                clean_slab_energies=state.get(
                    "clean_slab_energies",
                    {},
                ),
                reference_energies=state.get(
                    "reference_energies",
                    {},
                ),
            )
        )
        return {
            "adsorption_energy_calculation": calculation,
            "adsorption_energy_drafts": calculation.get(
                "calculations",
                [],
            ),
            "status": calculation.get(
                "status",
                "adsorption_energy_failed",
            ),
        }
    except Exception as error:
        return {
            "adsorption_energy_calculation": {
                "schema_version": "c12.7",
                "stage": "c12.7_adsorption_energy",
                "status": "adsorption_energy_failed",
                "calculations": [],
                "errors": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
            },
            "adsorption_energy_drafts": [],
            "status": "adsorption_energy_failed",
            "errors": _append_error(
                state=state,
                node="adsorption_energy_calculation",
                error=error,
            ),
        }


def adsorption_energy_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Pause for human review of C12.7 energy results."""

    calculations = state.get("adsorption_energy_drafts", [])
    if not isinstance(calculations, list):
        calculations = []

    if not calculations:
        return {
            "adsorption_energy_review": {
                "schema_version": "c12.7",
                "stage": "c12.7_adsorption_energy_review",
                "status": "adsorption_energy_review_skipped",
                "approved": [],
                "rejected": [],
                "deferred": [],
            },
            "approved_adsorption_energies": [],
            "status": "adsorption_energy_review_skipped",
        }

    decision = interrupt({
        "type": "adsorption_energy_review_required",
        "message": (
            "Review each three-energy subtraction and its "
            "reference-energy provenance."
        ),
        "calculations": calculations,
        "comparison_checks_performed": False,
        "requires_human_confirmation": True,
    })

    try:
        review = (
            services.adsorption_energy_review_gate.review(
                calculations,
                decision,
            )
        )
        return {
            "adsorption_energy_review": review,
            "approved_adsorption_energies": review.get(
                "approved",
                [],
            ),
            "status": review.get(
                "status",
                "adsorption_energy_review_failed",
            ),
        }
    except Exception as error:
        return {
            "adsorption_energy_review": {
                "schema_version": "c12.7",
                "stage": "c12.7_adsorption_energy_review",
                "status": "adsorption_energy_review_failed",
                "approved": [],
                "rejected": [],
                "deferred": [],
                "reason": str(error),
            },
            "approved_adsorption_energies": [],
            "status": "adsorption_energy_review_failed",
            "errors": _append_error(
                state=state,
                node="adsorption_energy_review",
                error=error,
            ),
        }


def submission_record_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Persist submitted Slurm jobs for monitoring."""

    submission = state.get(
        "remote_submission_result",
        {},
    )
    plan = state.get(
        "remote_execution_plan",
        {},
    )
    submitted_jobs = state.get(
        "submitted_dft_jobs",
        [],
    )

    if not isinstance(submitted_jobs, list):
        submitted_jobs = []

    try:
        result = (
            services.submitted_job_repository
            .record_submission(
                task_id=str(
                    state.get("task_id", "")
                ),
                job_source=str(
                    plan.get("job_source", "")
                ),
                plan_digest=str(
                    plan.get("plan_digest", "")
                ),
                jobs=submitted_jobs,
            )
        )

        from app.domain.workflow_run_repository import WorkflowRunRepository
        records = result.get("records", [])
        job_source = str(
            plan.get("job_source", "")
        )
        if job_source == "c12_5_adsorption":
            resume_stage = (
                "c12.6_adsorption_result_monitoring"
            )
        elif job_source == "c10_slab":
            resume_stage = (
                "c11.5.2_clean_slab_result_monitoring"
            )
        else:
            resume_stage = "formation_energy_backfill"

        task_context = {
            "task_analysis": state.get(
                "task_analysis",
                {},
            ),
            "reaction_profile": state.get(
                "reaction_profile",
                {},
            ),
            "papers": state.get("papers", []),
            "adsorption_user_overrides": state.get(
                "adsorption_user_overrides",
                {},
            ),
            "adsorption_literature_suggestions": state.get(
                "adsorption_literature_suggestions",
                [],
            ),
        }
        workflow = WorkflowRunRepository().update(
            str(state.get("task_id", "")),
            {
                "thread_id": str(state.get("task_id", "")),
                "workflow_status": "waiting_for_dft_results",
                "active_slurm_jobs": [
                    str(item["slurm_job_id"]) for item in records
                ],
                "resume_stage": resume_stage,
                "last_completed_stage": "submission_recording",
                "task_context": task_context,
                "terminal": False,
            },
        ) if records else {}

        return {
            "submission_recording": result,
            "persisted_cluster_jobs": result.get(
                "records",
                [],
            ),
            "workflow_run": workflow,
            "status": result.get(
                "status",
                "submission_recording_failed",
            ),
        }

    except Exception as error:
        return {
            "submission_recording": {
                "schema_version": "c11.5.1",
                "stage": "submission_recording",
                "status": "submission_recording_failed",
                "recorded_count": 0,
                "existing_count": 0,
                "failed_count": len(submitted_jobs),
                "records": [],
                "errors": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "submission_status": submission.get(
                        "status"
                    ),
                }],
                "next_stage": "c11.5.2_job_monitoring",
            },
            "persisted_cluster_jobs": [],
            "status": "submission_recording_failed",
            "errors": _append_error(
                state,
                "submission_recording",
                error,
            ),
        }


def stability_screening_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Apply the C7 formation-energy and delta/Omega criteria."""

    structures = state.get(
        "selected_formation_energy_structures",
        [],
    )

    if not isinstance(structures, list):
        structures = []

    try:
        result = (
            services.stability_screening_evaluator.evaluate(
                structures
            )
        )

        warnings = list(state.get("warnings", []))

        if result.get("pending_count", 0):
            warning = (
                "部分结构仍在等待 DFT 形成能，"
                "暂时不能进入 slab 生成。"
            )
            if warning not in warnings:
                warnings.append(warning)

        if result.get("evaluation_error_count", 0):
            warning = (
                "部分结构的 C7 稳定性计算失败，"
                "已禁止其进入 slab 生成。"
            )
            if warning not in warnings:
                warnings.append(warning)

        return {
            "stability_screening": result,
            "stability_screened_structures": (
                result.get("structures", [])
            ),
            "slab_eligible_structures": (
                result.get(
                    "slab_eligible_structures",
                    [],
                )
            ),
            "warnings": warnings,
            "status": result.get(
                "status",
                "stability_screening_failed",
            ),
        }

    except Exception as error:
        return {
            "stability_screening": {
                "schema_version": "c7.0",
                "stage": "c7",
                "status": "stability_screening_failed",
                "structure_count": len(structures),
                "passed_count": 0,
                "failed_count": 0,
                "pending_count": 0,
                "evaluation_error_count": 1,
                "structures": structures,
                "slab_eligible_structures": [],
                "errors": [{
                    "structure_id": "",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
                "slab_generated": False,
                "next_stage": "c8_slab_generation",
            },
            "stability_screened_structures": [],
            "slab_eligible_structures": [],
            "status": "stability_screening_failed",
            "errors": _append_error(
                state=state,
                node="stability_screening",
                error=error,
            ),
        }


def c7_dft_upgrade_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Let the user choose which C7-passed structures may enter C8 and DFT."""

    eligible = state.get("slab_eligible_structures", [])
    if not isinstance(eligible, list):
        eligible = []

    request = {
        "type": "c7_dft_upgrade_review_required",
        "schema_version": "c7.1",
        "message": (
            "C7 stability prescreening is complete. Select the passed "
            "structures that may continue to C8 slab generation and the "
            "subsequent DFT workflow."
        ),
        "structures": [{
            "structure_id": str(item.get("structure_id", "")),
            "candidate_id": str(item.get("candidate_id", "")),
            "composition": item.get("composition", {}),
            "formation_energy_ev_per_atom": item.get(
                "formation_energy_ev_per_atom",
                item.get(
                    "predicted_formation_energy_ev_per_atom",
                    item.get("formation_energy"),
                ),
            ),
            "delta_percent": item.get("delta_percent"),
            "omega": item.get("omega"),
            "cif_path": item.get("cif_path", ""),
            "poscar_path": item.get("poscar_path", ""),
        } for item in eligible],
        "passed_count": len(eligible),
        "safety_notice": (
            "This approval only permits preparation of C8-C11. Remote upload "
            "and sbatch submission still require their independent approvals."
        ),
    }
    decision = interrupt(request)
    if not isinstance(decision, dict):
        decision = {}

    selected_ids = {
        str(value).strip()
        for value in decision.get("select", decision.get("approve", []))
        if str(value).strip()
    }
    selected = [
        item for item in eligible
        if str(item.get("structure_id", "")).strip() in selected_ids
    ]
    known_ids = {
        str(item.get("structure_id", "")).strip() for item in eligible
    }
    unknown_ids = sorted(selected_ids - known_ids)
    review = {
        "schema_version": "c7.1",
        "status": (
            "c7_dft_upgrade_approved"
            if selected else "c7_dft_upgrade_not_approved"
        ),
        "eligible_count": len(eligible),
        "selected_count": len(selected),
        "selected_structure_ids": [
            str(item.get("structure_id", "")) for item in selected
        ],
        "unknown_structure_ids": unknown_ids,
        "rejected_structure_ids": list(decision.get("reject", [])),
        "deferred_structure_ids": list(decision.get("defer", [])),
        "note": str(decision.get("note", "")).strip(),
        "explicit_human_confirmation": True,
    }
    return {
        "c7_dft_upgrade_review": review,
        "dft_selected_stability_structures": selected,
        "slab_eligible_structures": selected,
        "c_stage_execution_mode": (
            "dft_validation" if selected else "stability_screening"
        ),
        "status": review["status"],
    }


def slab_generation_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Generate C8 FCC(111) slabs from C7-approved structures."""

    eligible = state.get(
        "slab_eligible_structures",
        [],
    )

    if not isinstance(eligible, list):
        eligible = []

    try:
        result = (
            services.slab_generation_service.generate(
                eligible
            )
        )

        warnings = list(state.get("warnings", []))

        if result.get("failure_count", 0):
            warning = (
                "部分通过 C7 的结构未能生成 48 原子 "
                "(111) slab，请查看 slab_generation.failures。"
            )
            if warning not in warnings:
                warnings.append(warning)

        return {
            "slab_generation": result,
            "generated_slabs": result.get(
                "slabs",
                [],
            ),
            "warnings": warnings,
            "status": result.get(
                "status",
                "slab_generation_failed",
            ),
        }

    except Exception as error:
        return {
            "slab_generation": {
                "schema_version": "c8.0",
                "stage": "c8",
                "status": "slab_generation_failed",
                "input_structure_count": len(eligible),
                "slab_count": 0,
                "failure_count": len(eligible),
                "slabs": [],
                "failures": [{
                    "structure_id": "",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
                "miller_index": [1, 1, 1],
                "expected_atom_count": 48,
                "vacuum_angstrom": 18.0,
                "stability_recalculated": False,
                "next_stage": "structure_visualization",
            },
            "generated_slabs": [],
            "status": "slab_generation_failed",
            "errors": _append_error(
                state=state,
                node="slab_generation",
                error=error,
            ),
        }


def slab_quality_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Inspect generated C8 slabs before human review."""

    slabs = state.get("generated_slabs", [])
    if not isinstance(slabs, list):
        slabs = []

    try:
        result = (
            services.slab_quality_inspector.inspect(
                slabs
            )
        )

        warnings = list(
            state.get("warnings", [])
        )

        if result.get("failed_count", 0):
            warning = (
                "部分 C8 slab 未通过 C9 自动质量检查，"
                "不会进入 DFT 人工确认。"
            )
            if warning not in warnings:
                warnings.append(warning)

        return {
            "slab_quality": result,
            "quality_passed_slabs": result.get(
                "quality_passed_slabs",
                [],
            ),
            "warnings": warnings,
            "status": result.get(
                "status",
                "slab_quality_failed",
            ),
        }

    except Exception as error:
        return {
            "slab_quality": {
                "schema_version": "c9.0",
                "stage": "c9_quality",
                "status": "slab_quality_failed",
                "input_slab_count": len(slabs),
                "checked_count": 0,
                "passed_count": 0,
                "failed_count": 0,
                "error_count": 1,
                "reports": [],
                "quality_passed_slabs": [],
                "errors": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
                "next_stage": "c9_slab_review",
            },
            "quality_passed_slabs": [],
            "status": "slab_quality_failed",
            "errors": _append_error(
                state=state,
                node="slab_quality",
                error=error,
            ),
        }


def slab_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Pause LangGraph for human slab approval."""

    slabs = state.get(
        "quality_passed_slabs",
        [],
    )
    if not isinstance(slabs, list):
        slabs = []

    if not slabs:
        return {
            "slab_review": {
                "schema_version": "c9.0",
                "stage": "c9_review",
                "status": "slab_review_skipped",
                "reviewed_count": 0,
                "approved_count": 0,
                "rejected_count": 0,
                "deferred_count": 0,
                "approved": [],
                "rejected": [],
                "deferred": [],
                "approved_for_dft": False,
                "reason": (
                    "No slab passed C9 automatic "
                    "quality inspection."
                ),
                "next_stage": "dft_input_preparation",
            },
            "dft_approved_slabs": [],
            "status": "slab_review_skipped",
        }

    review_request = {
        "type": "slab_review_required",
        "message": (
            "请检查通过自动质量判据的 slab，"
            "确认是否允许进入未来 DFT 输入准备。"
        ),
        "task_id": state.get("task_id", ""),
        "max_approved": (
            services.slab_review_gate.max_approved
        ),
        "instructions": {
            "approve": "批准进入未来 DFT 阶段。",
            "reject": "本任务中拒绝该 slab。",
            "defer": "暂缓，等待进一步人工检查。",
        },
        "slabs": [
            {
                "slab_id": slab.get("slab_id"),
                "candidate_id": slab.get(
                    "candidate_id"
                ),
                "atom_count": slab.get(
                    "atom_count"
                ),
                "element_count": slab.get(
                    "element_count"
                ),
                "minimum_distance_angstrom": (
                    slab.get(
                        "minimum_distance_angstrom"
                    )
                ),
                "measured_vacuum_angstrom": (
                    slab.get(
                        "measured_vacuum_angstrom"
                    )
                ),
                "fixed_atom_count": slab.get(
                    "fixed_atom_count"
                ),
                "movable_atom_count": slab.get(
                    "movable_atom_count"
                ),
                "failed_checks": slab.get(
                    "failed_checks",
                    [],
                ),
                "cif_path": slab.get("cif_path"),
                "poscar_path": slab.get(
                    "poscar_path"
                ),
            }
            for slab in slabs
        ],
    }

    decision = interrupt(review_request)

    try:
        result = services.slab_review_gate.review(
            slabs=slabs,
            decision=decision,
        )

        approved = result.get("approved", [])

        return {
            "slab_review": result,
            "dft_approved_slabs": approved,
            "status": (
                "slab_review_completed"
                if approved
                else "slab_review_completed_no_approval"
            ),
        }

    except Exception as error:
        return {
            "slab_review": {
                "schema_version": "c9.0",
                "stage": "c9_review",
                "status": "slab_review_failed",
                "approved": [],
                "reason": str(error),
            },
            "dft_approved_slabs": [],
            "status": "slab_review_failed",
            "errors": _append_error(
                state=state,
                node="slab_review",
                error=error,
            ),
        }


def dft_input_preview_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Create in-memory VASP previews from approved slabs."""

    slabs = state.get("dft_approved_slabs", [])
    if not isinstance(slabs, list):
        slabs = []

    try:
        result = (
            services.vasp_input_bundle_service.preview(
                approved_slabs=slabs,
                task_id=str(state.get("task_id", "")),
            )
        )

        return {
            "dft_input_preview": result,
            "status": result.get(
                "status",
                "dft_input_preview_failed",
            ),
        }

    except Exception as error:
        return {
            "dft_input_preview": {
                "schema_version": "c10.0",
                "stage": "c10_preview",
                "status": "dft_input_preview_failed",
                "bundle_count": 0,
                "bundles": [],
                "reason": str(error),
            },
            "status": "dft_input_preview_failed",
            "errors": _append_error(
                state=state,
                node="dft_input_preview",
                error=error,
            ),
        }


def dft_input_review_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Pause LangGraph for five-file VASP review."""

    preview = state.get("dft_input_preview", {})
    bundles = preview.get("bundles", [])

    if not isinstance(bundles, list):
        bundles = []

    if not bundles:
        return {
            "dft_input_review": {
                "schema_version": "c10.0",
                "status": "dft_input_review_skipped",
                "approve": [],
                "reject": [],
                "defer": [],
                "file_confirmations": {},
            },
            "status": "dft_input_review_skipped",
        }

    decision = interrupt({
        "type": "dft_input_review_required",
        "message": (
            "请逐项检查五个 VASP 文件。"
            "全部确认后才会生成正式计算目录。"
        ),
        "bundles": bundles,
        "revision_count": state.get("dft_revision_count", 0),
        "revision_validation": state.get(
            "dft_revision_validation", {}
        ),
    })

    return {
        "dft_input_review": decision,
        "dft_revision_request": decision.get(
            "revision_requests", {}
        ),
        "status": "dft_input_review_completed",
    }


def dft_revision_plan_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Translate a natural-language C10 revision into structured JSON."""

    try:
        result = services.dft_input_revision_service.parse_requests(
            revision_requests=state.get("dft_revision_request", {}),
            preview=state.get("dft_input_preview", {}),
        )
        return {
            "dft_revision_plan": result,
            "dft_revision_validation": {},
            "status": "dft_revision_plan_ready",
        }
    except Exception as error:
        return {
            "dft_revision_plan": {},
            "dft_revision_validation": {
                "schema_version": "c10-revision-v1",
                "status": "dft_revision_rejected",
                "reason": str(error),
                "poscar_unchanged": True,
            },
            "status": "dft_revision_rejected",
            "errors": _append_error(
                state=state,
                node="dft_revision_plan",
                error=error,
            ),
        }


def dft_revision_apply_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Validate and apply a structured revision without touching POSCAR."""

    plan = state.get("dft_revision_plan", {})
    if not plan:
        return {
            "status": "dft_revision_rejected",
        }

    try:
        result = services.dft_input_revision_service.apply(
            preview=state.get("dft_input_preview", {}),
            plan=plan,
            revision_count=int(state.get("dft_revision_count", 0)),
            history=state.get("dft_revision_history", []),
        )
        return {
            "dft_input_preview": result["preview"],
            "dft_revision_validation": result["validation"],
            "dft_revision_history": result["history"],
            "dft_revision_count": result["revision_count"],
            "dft_input_review": {},
            "status": "dft_revision_accepted",
        }
    except Exception as error:
        return {
            "dft_revision_validation": {
                "schema_version": "c10-revision-v1",
                "status": "dft_revision_rejected",
                "reason": str(error),
                "poscar_unchanged": True,
            },
            "status": "dft_revision_rejected",
            "errors": _append_error(
                state=state,
                node="dft_revision_apply",
                error=error,
            ),
        }


def dft_input_finalize_node(
    state: CatalystState,
) -> dict[str, Any]:
    """Finalize reviewed VASP bundles atomically."""

    preview = state.get("dft_input_preview", {})
    review = state.get("dft_input_review", {})

    try:
        result = (
            services.vasp_input_bundle_service.finalize(
                preview=preview,
                review=review,
            )
        )

        return {
            "dft_input_preparation": result,
            "dft_jobs": result.get("jobs", []),
            "status": result.get(
                "status",
                "dft_input_preparation_failed",
            ),
        }

    except Exception as error:
        return {
            "dft_input_preparation": {
                "schema_version": "c10.0",
                "stage": "c10_finalize",
                "status": "dft_input_preparation_failed",
                "jobs": [],
                "failures": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
            },
            "dft_jobs": [],
            "status": "dft_input_preparation_failed",
            "errors": _append_error(
                state=state,
                node="dft_input_finalize",
                error=error,
            ),
        }


def _candidate_review_summary(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Keep only fields needed by the candidate review UI."""

    details = candidate.get("details", {})
    literature_detail = details.get("literature_support", {})
    best_evidence = literature_detail.get("best_evidence")
    toxicity_detail = details.get("toxicity_environment", {})
    synthesis_detail = details.get("synthesis_difficulty", {})

    return {
        "candidate_id": candidate.get("candidate_id", ""),
        "rank": candidate.get("rank"),
        "elements": candidate.get("elements", []),
        "composition": candidate.get("composition", {}),
        "total_score": candidate.get("total_score", 0.0),
        "scores": candidate.get("scores", {}),
        "best_literature_evidence": best_evidence,
        "highest_risk_elements": toxicity_detail.get(
            "highest_risk_elements",
            [],
        ),
        "active_process_risks": synthesis_detail.get(
            "active_process_risks",
            {},
        ),
        "requires_human_confirmation": True,
    }


def _review_candidate(
    paper: dict[str, Any],
) -> dict[str, Any]:
    """裁剪人工审查界面需要展示的论文信息。"""

    quality = paper.get(
        "evidence_quality",
        {},
    )

    version_info = paper.get(
        "version_info",
        {},
    )
    verification_level = literature_verification_level(paper)

    return {
        "evidence_id": paper.get(
            "evidence_id",
            "",
        ),
        "paper_id": paper.get(
            "paper_id",
            "",
        ),
        "title": paper.get(
            "title",
            "未提供标题",
        ),
        "year": paper.get("year"),
        "journal": paper.get(
            "journal",
            "",
        ),
        "doi": paper.get(
            "doi",
            "",
        ),
        "url": paper.get(
            "url",
            "",
        ),
        "abstract": paper.get(
            "abstract",
            "",
        ),
        "source": paper.get(
            "source",
            "",
        ),
        "retrieval_origin": paper.get(
            "retrieval_origin",
            "",
        ),
        "quality_level": quality.get(
            "quality_level",
            "D",
        ),
        "quality_score": quality.get(
            "quality_score",
            0,
        ),
        "quality_score_max": quality.get("quality_score_max", 100),
        "score_weights": quality.get("score_weights", {}),
        "metadata_quality": quality.get("metadata_quality", {}),
        "task_relevance": quality.get("task_relevance", {}),
        "claim_evidence_quality": quality.get(
            "claim_evidence_quality", {}
        ),
        "journal_impact": quality.get("journal_impact", {}),
        "metadata_verified": paper.get("metadata_verified", False),
        "metadata_provider": paper.get("metadata_provider", ""),
        "cross_verified": bool(
            paper.get("cross_verified", False)
            or paper.get("kimi_cross_verified", False)
        ),
        "cross_verification": paper.get("cross_verification", {}),
        "verification_level": verification_level,
        "secondary_verification_pending": verification_level == "single_source",
        "reaction_direct": bool(quality.get("reaction_direct", False)),
        "target_product_required": False,
        "c_stage_evidence_eligible": bool(
            verification_level in {"dual_source", "single_source"}
            and quality.get("reaction_direct", False)
        ),
        "assertions": paper.get("assertions", []),
        "claim_evidence_available": paper.get(
            "claim_evidence_available", bool(paper.get("abstract"))
        ),
        "composition_elements": quality.get("composition_elements", []),
        "composition_element_count": quality.get(
            "composition_element_count", 0
        ),
        "hea_composition_eligible": quality.get(
            "hea_composition_eligible", False
        ),
        "common_hea_transition_metals": quality.get(
            "common_hea_transition_metals", []
        ),
        "quality_issues": quality.get(
            "issues",
            [],
        ),
        "version_info": version_info,
        "review_status": paper.get(
            "review_status",
            "pending_review",
        ),
    }


def _unique_strings(
    values: list[Any],
) -> list[str]:
    """删除空字符串和重复项，同时保持顺序。"""

    result: list[str] = []

    for value in values:
        text = str(value).strip()

        if text and text not in result:
            result.append(text)

    return result


def _append_error(
    state: CatalystState,
    node: str,
    error: Exception,
) -> list[dict[str, Any]]:
    """保留旧错误，并追加新的节点异常。"""

    errors = list(
        state.get("errors", [])
    )

    errors.append(
        {
            "node": node,
            "type": type(error).__name__,
            "message": str(error),
        }
    )

    return errors


def _append_message(
    state: CatalystState,
    node: str,
    error_type: str,
    message: str,
) -> list[dict[str, Any]]:
    """追加一个不依赖异常对象的错误。"""

    errors = list(
        state.get("errors", [])
    )

    errors.append(
        {
            "node": node,
            "type": error_type,
            "message": message,
        }
    )

    return errors
