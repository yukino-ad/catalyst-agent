from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.llm_client import LLMError, OpenAICompatibleClient
from tools.literature.repository import LiteratureRepository


class LiteratureRAG:
    """Evidence-first local RAG with an optional LLM synthesis step."""

    def __init__(
        self,
        corpus_path: str | Path = "data/papers/sample_papers.json",
        db_path: str | Path = "database/literature/literature.db",
        llm: OpenAICompatibleClient | None = None,
    ) -> None:
        path = Path(corpus_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        self.corpus_path = path
        self.llm = llm or OpenAICompatibleClient()
        self.repository = LiteratureRepository(db_path)
        self.documents = json.loads(path.read_text(encoding="utf-8"))

    def retrieve(self, query: str, keywords: list[str], top_k: int = 4) -> list[dict[str, Any]]:
        if self.repository.count():
            database_hits = self.repository.search(query + " " + " ".join(keywords), top_k=top_k)
            return [self._database_evidence(item, index) for index, item in enumerate(database_hits, 1)]
        query_terms = self._terms(" ".join([query, *keywords]))
        hits = []
        for index, document in enumerate(self.documents):
            searchable = " ".join(
                [
                    document.get("title", ""),
                    " ".join(document.get("keywords", [])),
                    " ".join(document.get("elements", [])),
                    " ".join(document.get("adsorbates", [])),
                    " ".join(document.get("insights", [])),
                ]
            )
            document_terms = self._terms(searchable)
            matched = sorted(query_terms & document_terms)
            phrase_bonus = sum(
                2 for keyword in keywords if keyword.lower() in searchable.lower()
            )
            score = len(matched) + phrase_bonus
            if score:
                hits.append(
                    {
                        "evidence_id": f"E{index + 1}",
                        "score": score,
                        "matched_terms": matched,
                        **document,
                    }
                )
        hits.sort(key=lambda item: (-item["score"], -int(item.get("year", 0))))
        return hits[:top_k]

    @staticmethod
    def _database_evidence(document: dict[str, Any], index: int) -> dict[str, Any]:
        elements: list[str] = []
        adsorbates: list[str] = []
        insights = [document.get("summary", "")] if document.get("summary") else []
        for assertion in document.get("assertions", []):
            value = assertion.get("value", [])
            values = value if isinstance(value, list) else [value]
            if assertion.get("kind") == "element_set":
                elements.extend(str(item) for item in values)
            elif assertion.get("kind") == "intermediate":
                adsorbates.extend(str(item) for item in values)
            evidence_quotes = [item.get("quote", "") for item in assertion.get("evidence", [])]
            insights.extend(quote for quote in evidence_quotes if quote)
        return {
            "evidence_id": f"E{index}",
            "paper_id": document.get("paper_id"),
            "title": document.get("title", ""),
            "abstract": document.get("abstract", ""),
            "year": document.get("year"),
            "journal": document.get("journal", ""),
            "doi": document.get("doi", ""),
            "url": document.get("url", ""),
            "score": document.get("score", 0),
            "matched_terms": document.get("matched_terms", []),
            "elements": list(dict.fromkeys(elements)),
            "adsorbates": list(dict.fromkeys(adsorbates)),
            "insights": list(dict.fromkeys(insights)),
            "assertions": document.get("assertions", []),
        }

    def answer(self, question: str, plan: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        if not evidence:
            return {
                "answer": "本地文献库中没有检索到足够证据，暂不生成材料结论。",
                "citations": [],
                "mode": "no_evidence",
            }
        if self.llm.available:
            try:
                return self._llm_answer(question, plan, evidence)
            except LLMError as error:
                fallback = self._extractive_answer(evidence)
                fallback["warning"] = str(error)
                return fallback
        return self._extractive_answer(evidence)

    def run(self, question: str, plan: dict[str, Any], top_k: int = 4) -> dict[str, Any]:
        evidence = self.retrieve(question, plan.get("keywords", []), top_k=top_k)
        synthesis = self.answer(question, plan, evidence)
        return {"evidence": evidence, "synthesis": synthesis}

    def _llm_answer(
        self, question: str, plan: dict[str, Any], evidence: list[dict[str, Any]]
    ) -> dict[str, Any]:
        blocks = []
        for item in evidence:
            blocks.append(
                f"[{item['evidence_id']}] {item['title']} ({item.get('year', 'n.d.')})\n"
                f"DOI: {item.get('doi') or 'not available'}\n"
                f"URL: {item.get('url') or 'not available'}\n"
                f"Abstract: {item.get('abstract') or 'abstract not available'}\n"
                f"Elements: {', '.join(item.get('elements', []))}\n"
                f"Adsorbates: {', '.join(item.get('adsorbates', []))}\n"
                f"Insights: {'; '.join(item.get('insights', []))}"
            )
        text = self.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是材料文献 RAG 助手。只能使用提供的证据，不得补充未出现的论文、数据或结论。"
                        "每个关键判断后必须引用 [E1] 形式的证据编号。"
                        "区分文献证据、合理假设和仍需 DFT 验证的内容。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"问题：{question}\n目标：{plan.get('objective')}\n\n证据：\n"
                        + "\n\n".join(blocks)
                        + "\n\n请先输出证据目录，逐条列出 [E编号]、论文标题、DOI 和摘要原文；"
                        "随后输出文献结论、候选元素启发、关键描述符、风险与下一步验证。"
                    ),
                },
            ],
            temperature=1.0,
            max_tokens=1600,
        )
        citations = sorted(set(re.findall(r"\[(E\d+)\]", text)))
        answer = self._evidence_catalog(evidence) + "\n\n" + text
        return {"answer": answer, "citations": citations, "mode": "llm_rag"}

    @staticmethod
    def _extractive_answer(evidence: list[dict[str, Any]]) -> dict[str, Any]:
        lines = []
        for item in evidence:
            insights = item.get("insights", [])
            if insights:
                lines.append(f"[{item['evidence_id']}] {insights[0]}")
        return {
            "answer": LiteratureRAG._evidence_catalog(evidence) + "\n\n" + "\n".join(lines),
            "citations": [item["evidence_id"] for item in evidence],
            "mode": "extractive_fallback",
        }

    @staticmethod
    def _evidence_catalog(evidence: list[dict[str, Any]]) -> str:
        sections = ["证据目录（请人工复核 DOI 和摘要原文）"]
        for item in evidence:
            sections.extend([
                f"[{item['evidence_id']}] {item.get('title') or '未提供标题'}",
                f"DOI: {item.get('doi') or '未提供'}",
                f"URL: {item.get('url') or '未提供'}",
                f"摘要原文: {item.get('abstract') or '未提供摘要'}",
                "",
            ])
        return "\n".join(sections).rstrip()

    @staticmethod
    def _terms(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9*+-]{2,}|[\u4e00-\u9fff]{2,}", text.lower()))
