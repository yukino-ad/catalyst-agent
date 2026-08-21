from __future__ import annotations

import json
import re
import time
from difflib import SequenceMatcher
from typing import Any

from tools.literature.academic_search_tools import (
    ACADEMIC_SEARCH_TOOLS,
    AcademicSearchToolRegistry,
)
from tools.literature.retry_support import normalize_doi, normalize_title
from tools.llm_client import LLMError, OpenAICompatibleClient


B4_KIMI_ACADEMIC_SEARCH_SYSTEM_PROMPT = """你是B阶段学术文献检索规划器。

你必须使用已注册的学术搜索工具完成检索，不能依靠模型记忆提供论文。
至少调用一次 search_crossref 和一次 search_semantic_scholar。

目标是寻找与指定电催化反应和高熵合金相关的论文。

优先寻找：
1. 明确属于 high-entropy alloy；
2. 同一篇论文中明确给出五种金属；
3. 明确涉及目标反应；
4. 有 DOI、题名、期刊、年份和可追溯 URL；
5. 有摘要或其他可引用原文。

禁止：
1. 编造 DOI、题名、期刊、年份或性能数据；
2. 将多篇论文中的元素拼成一个五元组合；
3. 根据材料常识补充论文没有写出的元素；
4. 把搜索摘要片段当作论文结论原文；
5. 将未调用工具的模型记忆描述为联网检索结果。

Crossref负责核验正式出版元数据。
Semantic Scholar负责补充摘要、引用信息和开放获取链接。
只有两个来源通过 DOI 或规范化题名匹配的论文才能标记为 cross_verified。

完成两个工具调用后，只输出JSON对象，包含 search_summary、candidate_dois 和 warnings。
candidate_dois只能引用工具结果中真实存在的DOI。"""


class KimiCrossrefVerifier:
    """Run Kimi's registered tools and deterministically cross-verify papers."""

    SCHEMA_VERSION = "kimi-academic-tools-v1"
    MAX_STEPS = 6
    TOOL_RESULT_LIMIT = 8
    ABSTRACT_LIMIT = 600
    TRANSIENT_RETRY_DELAYS = (1.0, 3.0)

    def __init__(
        self,
        llm: OpenAICompatibleClient | None = None,
        registry: AcademicSearchToolRegistry | None = None,
    ) -> None:
        self.llm = llm or OpenAICompatibleClient()
        self.registry = registry or AcademicSearchToolRegistry()

    def verify(
        self,
        papers: list[dict[str, Any]],
        task_analysis: dict[str, Any],
        question: str,
    ) -> dict[str, Any]:
        if not papers:
            return self._result("no_candidates", papers, [], [], "")
        if not self.llm.available:
            return self._result(
                "kimi_unavailable",
                papers,
                [],
                [],
                "",
                ["Kimi is unavailable; dual-source tool search was not run."],
            )

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": B4_KIMI_ACADEMIC_SEARCH_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": self._request_prompt(question, task_analysis, papers),
            },
        ]
        calls: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        final_content = ""
        warnings: list[str] = []
        try:
            for _step in range(self.MAX_STEPS):
                response = self._chat_with_retry(messages)
                assistant_message = {
                    "role": "assistant",
                    "content": response.get("content", ""),
                }
                response_calls = response.get("tool_calls", [])
                if response_calls:
                    assistant_message["tool_calls"] = response_calls
                messages.append(assistant_message)
                if not response_calls:
                    final_content = str(response.get("content", "") or "")
                    missing = self._missing_tools(calls)
                    if missing:
                        messages.append({
                            "role": "user",
                            "content": (
                                "尚未完成必需工具调用。现在必须调用："
                                + ", ".join(sorted(missing))
                                + "。不得直接给出最终答案。"
                            ),
                        })
                        continue
                    break
                for call in response_calls:
                    result = self._execute_call(call)
                    calls.append(result["audit"])
                    tool_results.append(result["result"])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": result["call_id"],
                        "name": result["name"],
                        "content": json.dumps(
                            self._compact_tool_result(
                                result["result"],
                                self._missing_tools(calls),
                            ),
                            ensure_ascii=False,
                        ),
                    })
            else:
                warnings.append("Kimi academic search reached the six-step limit.")
        except (LLMError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            warnings.append(f"Kimi academic tool search failed: {error}")

        used = {call["name"] for call in calls if call.get("status") == "completed"}
        required = {"search_crossref", "search_semantic_scholar"}
        status = "completed" if required <= used else "required_tools_missing"
        if status != "completed":
            warnings.append(
                "Kimi did not successfully call both required academic search tools."
            )
        return self._result(
            status,
            papers,
            calls,
            tool_results,
            final_content,
            warnings,
        )

    def _chat_with_retry(
        self,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        for attempt in range(len(self.TRANSIENT_RETRY_DELAYS) + 1):
            try:
                return self.llm.chat_with_tools(
                    messages=messages,
                    tools=ACADEMIC_SEARCH_TOOLS,
                    max_tokens=1200,
                    timeout_seconds=90,
                )
            except LLMError as error:
                if not self._is_transient(error) or attempt >= len(
                    self.TRANSIENT_RETRY_DELAYS
                ):
                    raise
                time.sleep(self.TRANSIENT_RETRY_DELAYS[attempt])
        raise RuntimeError("Kimi retry loop ended unexpectedly")

    @staticmethod
    def _is_transient(error: Exception) -> bool:
        message = str(error).lower()
        return any(
            marker in message
            for marker in ("http 500", "http 502", "http 503", "http 504")
        )

    @staticmethod
    def _missing_tools(calls: list[dict[str, Any]]) -> set[str]:
        used = {
            str(call.get("name", ""))
            for call in calls
            if call.get("status") == "completed"
        }
        return {"search_crossref", "search_semantic_scholar"} - used

    def _compact_tool_result(
        self,
        result: dict[str, Any],
        missing_tools: set[str],
    ) -> dict[str, Any]:
        papers = []
        for paper in result.get("papers", [])[: self.TOOL_RESULT_LIMIT]:
            if not isinstance(paper, dict):
                continue
            papers.append({
                "paper_id": paper.get("paper_id", ""),
                "doi": normalize_doi(paper.get("doi", "")),
                "title": paper.get("title", ""),
                "journal": paper.get("journal", ""),
                "year": paper.get("year"),
                "url": paper.get("url", ""),
                "abstract": str(paper.get("abstract", "") or "")[
                    : self.ABSTRACT_LIMIT
                ],
            })
        return {
            "provider": result.get("provider", ""),
            "query": result.get("query", ""),
            "count": result.get("count", len(papers)),
            "returned_to_model_count": len(papers),
            "papers": papers,
            "next_required_tools": sorted(missing_tools),
        }

    def _execute_call(self, call: dict[str, Any]) -> dict[str, Any]:
        call_id = str(call.get("id", "") or "")
        function = call.get("function", {})
        if not call_id or not isinstance(function, dict):
            raise ValueError("Malformed Kimi tool call")
        name = str(function.get("name", "") or "")
        raw_arguments = function.get("arguments", "{}")
        arguments = (
            json.loads(raw_arguments)
            if isinstance(raw_arguments, str)
            else raw_arguments
        )
        result = self.registry.execute(name, arguments)
        return {
            "call_id": call_id,
            "name": name,
            "result": result,
            "audit": {
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
                "provider": result.get("provider", ""),
                "result_count": result.get("count", 0),
                "status": "completed",
            },
        }

    def _result(
        self,
        status: str,
        papers: list[dict[str, Any]],
        calls: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
        final_content: str,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        crossref = self._provider_papers(tool_results, "crossref")
        semantic = self._provider_papers(tool_results, "semantic_scholar")
        both_tools_used = {
            call.get("name") for call in calls if call.get("status") == "completed"
        } >= {"search_crossref", "search_semantic_scholar"}
        annotated = []
        verified_count = 0
        for original in papers:
            paper = dict(original)
            crossref_match, crossref_method = self._best_match(paper, crossref)
            semantic_match, semantic_method = self._best_match(paper, semantic)
            cross_verified = bool(
                both_tools_used and crossref_match and semantic_match
            )
            if semantic_match:
                if not paper.get("abstract") and semantic_match.get("abstract"):
                    paper["abstract"] = semantic_match["abstract"]
                paper["semantic_scholar_id"] = semantic_match.get(
                    "semantic_scholar_id", ""
                )
                paper["citation_count"] = semantic_match.get("citation_count", 0)
                paper["open_access_pdf_url"] = semantic_match.get(
                    "open_access_pdf_url", ""
                )
            paper["claim_evidence_available"] = bool(paper.get("abstract"))
            paper["kimi_web_search_performed"] = bool(calls)
            paper["kimi_cross_verified"] = cross_verified
            paper["cross_verified"] = cross_verified
            paper["cross_verification"] = {
                "crossref_verified": bool(crossref_match),
                "semantic_scholar_verified": bool(semantic_match),
                "crossref_match_method": crossref_method,
                "semantic_scholar_match_method": semantic_method,
                "required_tools_called": both_tools_used,
                "cross_verified": cross_verified,
            }
            verified_count += int(cross_verified)
            annotated.append(paper)
        return {
            "schema_version": self.SCHEMA_VERSION,
            "status": status,
            "required_tools_called": both_tools_used,
            "tool_call_count": len(calls),
            "tool_calls": calls,
            "crossref_result_count": len(crossref),
            "semantic_scholar_result_count": len(semantic),
            "candidate_count": len(papers),
            "mutually_verified_count": verified_count,
            "papers": annotated,
            "kimi_final_content": final_content,
            "warnings": list(dict.fromkeys(warnings or [])),
        }

    @staticmethod
    def _provider_papers(
        results: list[dict[str, Any]], provider: str
    ) -> list[dict[str, Any]]:
        return [
            paper
            for result in results
            if result.get("provider") == provider
            for paper in result.get("papers", [])
            if isinstance(paper, dict)
        ]

    @classmethod
    def _best_match(
        cls,
        paper: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, str]:
        doi = normalize_doi(paper.get("doi", ""))
        for candidate in candidates:
            if doi and normalize_doi(candidate.get("doi", "")) == doi:
                return candidate, "doi_exact"
        title = normalize_title(paper.get("title", ""))
        year = paper.get("year")
        best = None
        best_score = 0.0
        for candidate in candidates:
            candidate_title = normalize_title(candidate.get("title", ""))
            score = SequenceMatcher(None, title, candidate_title).ratio()
            candidate_year = candidate.get("year")
            year_ok = (
                year is None
                or candidate_year is None
                or abs(int(year) - int(candidate_year)) <= 1
            )
            if score >= 0.92 and year_ok and score > best_score:
                best = candidate
                best_score = score
        return (best, f"title_year:{best_score:.3f}") if best else (None, "none")

    @staticmethod
    def _request_prompt(
        question: str,
        task: dict[str, Any],
        papers: list[dict[str, Any]],
    ) -> str:
        seed = [{
            "doi": normalize_doi(paper.get("doi", "")),
            "title": paper.get("title", ""),
            "journal": paper.get("journal", ""),
            "year": paper.get("year"),
        } for paper in papers[:10]]
        return (
            f"用户任务：{question}\n"
            f"目标反应：{task.get('reaction_family', '')}\n"
            f"材料类型：{task.get('material_family', '')}\n"
            f"Crossref基线候选：{json.dumps(seed, ensure_ascii=False)}\n"
            "请先围绕任务调用两个工具进行独立检索，再根据工具结果收敛。"
        )


__all__ = [
    "B4_KIMI_ACADEMIC_SEARCH_SYSTEM_PROMPT",
    "KimiCrossrefVerifier",
]
