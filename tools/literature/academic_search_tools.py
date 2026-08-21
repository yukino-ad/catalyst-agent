from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from tools.literature.crossref_client import CrossrefClient
from tools.literature.semantic_scholar_client import SemanticScholarClient


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


ACADEMIC_SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_crossref",
            "description": (
                "Search Crossref for traceable journal metadata and verify DOI, "
                "title, journal, and publication year."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "English bibliographic query containing reaction "
                            "and high-entropy-alloy terms."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 10,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_semantic_scholar",
            "description": (
                "Search Semantic Scholar for abstracts, external IDs, citations, "
                "and open-access links."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "English scholarly literature query.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 10,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]


class AcademicSearchToolRegistry:
    """Execute only explicitly registered academic search functions."""

    def __init__(
        self,
        crossref: CrossrefClient | None = None,
        semantic_scholar: SemanticScholarClient | None = None,
    ) -> None:
        self.crossref = crossref or CrossrefClient()
        self.semantic_scholar = semantic_scholar or SemanticScholarClient()

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise TypeError("Academic tool arguments must be an object")
        query = str(arguments.get("query", "") or "").strip()
        if not query:
            raise ValueError("Academic search query must not be empty")
        if len(query) > 500:
            raise ValueError("Academic search query exceeds 500 characters")
        try:
            limit = int(arguments.get("limit", 10))
        except (TypeError, ValueError) as error:
            raise ValueError("Academic search limit must be an integer") from error
        limit = max(1, min(limit, 20))

        if name == "search_crossref":
            records = self.crossref.search(
                query=query,
                per_page=limit,
                mailto=os.getenv("CROSSREF_MAILTO", ""),
            )
            return {
                "provider": "crossref",
                "query": query,
                "count": len(records),
                "papers": [record.to_dict() for record in records],
            }
        if name == "search_semantic_scholar":
            return self.semantic_scholar.search(query=query, limit=limit)
        raise ValueError(f"Unsupported academic search tool: {name}")


__all__ = ["ACADEMIC_SEARCH_TOOLS", "AcademicSearchToolRegistry"]
