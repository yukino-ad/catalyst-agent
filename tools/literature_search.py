from __future__ import annotations

from tools.literature_rag import LiteratureRAG


class LiteratureSearchTool:
    """Compatibility wrapper around the local evidence retriever."""

    def __init__(self) -> None:
        self.rag = LiteratureRAG()

    def search(self, keywords: list[str]) -> list[dict]:
        return self.rag.retrieve(" ".join(keywords), keywords, top_k=5)

