from __future__ import annotations

import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any

from tools.literature.schemas import PaperRecord


class LiteratureRepository:
    def __init__(self, db_path: str | Path = "database/literature/literature.db") -> None:
        path = Path(db_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = path
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    paper_id TEXT PRIMARY KEY, title TEXT NOT NULL, abstract TEXT NOT NULL DEFAULT '',
                    year INTEGER, journal TEXT, doi TEXT, url TEXT, source TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '', raw_json TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS assertions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT NOT NULL,
                    kind TEXT NOT NULL, value_json TEXT NOT NULL, evidence_level TEXT NOT NULL,
                    confidence TEXT NOT NULL, inferred INTEGER NOT NULL DEFAULT 0,
                    evidence_json TEXT NOT NULL, FOREIGN KEY(paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS extraction_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT NOT NULL, model TEXT,
                    prompt_version TEXT, status TEXT NOT NULL, error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_assertions_kind ON assertions(kind);
                CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
                """
            )

    def upsert(self, paper: PaperRecord) -> None:
        raw_json = json.dumps(paper.to_dict(), ensure_ascii=False)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO papers(paper_id,title,abstract,year,journal,doi,url,source,summary,raw_json)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(paper_id) DO UPDATE SET
                title=excluded.title, abstract=excluded.abstract, year=excluded.year,
                journal=excluded.journal, doi=excluded.doi, url=excluded.url,
                source=excluded.source, summary=excluded.summary, raw_json=excluded.raw_json,
                updated_at=CURRENT_TIMESTAMP""",
                (paper.paper_id, paper.title, paper.abstract, paper.year, paper.journal,
                 paper.doi, paper.url, paper.source, paper.summary, raw_json),
            )
            connection.execute("DELETE FROM assertions WHERE paper_id=?", (paper.paper_id,))
            for assertion in paper.assertions:
                connection.execute(
                    """INSERT INTO assertions(paper_id,kind,value_json,evidence_level,confidence,inferred,evidence_json)
                    VALUES(?,?,?,?,?,?,?)""",
                    (paper.paper_id, assertion.kind, json.dumps(assertion.value, ensure_ascii=False),
                     assertion.evidence_level, assertion.confidence, int(assertion.inferred),
                     json.dumps([e.__dict__ for e in assertion.evidence], ensure_ascii=False)),
                )

    def count(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0])

    def search(self, query: str, filters: dict[str, Any] | None = None, top_k: int = 5) -> list[dict[str, Any]]:
        filters = filters or {}
        with self.connect() as connection:
            rows = connection.execute("SELECT raw_json FROM papers").fetchall()
        documents = [json.loads(row[0]) for row in rows]
        required = [str(value).lower() for value in filters.values() if value]
        if required:
            documents = [doc for doc in documents if all(value in json.dumps(doc, ensure_ascii=False).lower() for value in required)]
        terms = self._terms(query)
        if not documents:
            return []
        document_terms = [self._terms(doc.get("embedding_text", "")) for doc in documents]
        frequency = {term: sum(term in item for item in document_terms) for term in terms}
        scored = []
        for doc, tokens in zip(documents, document_terms):
            matched = sorted(terms & tokens)
            score = sum(math.log((len(documents) + 1) / (frequency[term] + 1)) + 1 for term in matched)
            if score or not terms:
                doc["score"] = round(score, 4)
                doc["matched_terms"] = matched
                scored.append(doc)
        scored.sort(key=lambda item: (-item["score"], -(item.get("year") or 0)))
        return scored[:top_k]

    @staticmethod
    def _terms(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9*+-]{2,}|[\u4e00-\u9fff]{2,}", text.lower()))
