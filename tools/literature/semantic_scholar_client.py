from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class SemanticScholarRateLimitError(OSError):
    """Semantic Scholar requested an unsuitable interactive delay."""


class SemanticScholarClient:
    """Search Semantic Scholar Graph API with bounded retries and caching."""

    FIELDS = (
        "paperId,title,abstract,year,venue,url,externalIds,citationCount,"
        "isOpenAccess,openAccessPdf"
    )

    def __init__(
        self,
        cache_dir: str | Path = "database/literature/cache/semantic_scholar",
        raw_dir: str | Path = "database/literature/raw/semantic_scholar",
        timeout_seconds: int | None = None,
        cache_ttl_seconds: int = 86400,
        retry_delays: tuple[float, ...] = (3.0, 10.0),
        maximum_retry_after_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        root = Path(__file__).resolve().parents[2]
        self.cache_dir = self._directory(cache_dir, root)
        self.raw_dir = self._directory(raw_dir, root)
        self.timeout_seconds = timeout_seconds or int(
            os.getenv("SEMANTIC_SCHOLAR_TIMEOUT_SECONDS", "30")
        )
        self.cache_ttl_seconds = cache_ttl_seconds
        self.retry_delays = retry_delays
        self.maximum_retry_after_seconds = maximum_retry_after_seconds
        self.sleep = sleep

    @staticmethod
    def _directory(value: str | Path, root: Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            raise ValueError("Semantic Scholar query must not be empty")
        if not 1 <= limit <= 20:
            raise ValueError("Semantic Scholar limit must be between 1 and 20")
        cache_path = self._cache_path(query, limit)
        payload = self._read_cache(cache_path)
        if payload is None:
            payload = self._request(query, limit)
            cache_path.write_text(
                json.dumps(
                    {
                        "cached_at": datetime.now(timezone.utc).isoformat(),
                        "payload": payload,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            (self.raw_dir / f"search_{stamp}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        papers = [
            self._normalize(item)
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("title")
        ]
        return {
            "provider": "semantic_scholar",
            "query": query,
            "count": len(papers),
            "papers": papers,
        }

    def find_by_doi(self, doi: str) -> dict[str, Any] | None:
        """Return an exact DOI match, using the normal cached search path."""

        normalized = self._normalize_doi(doi)
        if not normalized:
            return None
        result = self.search(normalized, limit=5)
        for paper in result.get("papers", []):
            if self._normalize_doi(paper.get("doi", "")) == normalized:
                return paper
        return None

    @staticmethod
    def _normalize_doi(value: Any) -> str:
        doi = str(value or "").strip().lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if doi.startswith(prefix):
                doi = doi[len(prefix):]
        return doi.rstrip(".")

    def _request(self, query: str, limit: int) -> dict[str, Any]:
        parameters = urllib.parse.urlencode({
            "query": query,
            "limit": limit,
            "fields": self.FIELDS,
        })
        url = (
            "https://api.semanticscholar.org/graph/v1/paper/search?"
            + parameters
        )
        headers = {
            "Accept": "application/json",
            "User-Agent": "catalyst-agent/0.6",
        }
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
        if api_key:
            headers["x-api-key"] = api_key
        for attempt in range(len(self.retry_delays) + 1):
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_seconds
                ) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                if (
                    error.code not in {429, 500, 502, 503, 504}
                    or attempt >= len(self.retry_delays)
                ):
                    raise
                value = error.headers.get("Retry-After") if error.headers else None
                try:
                    delay = (
                        float(value)
                        if value is not None
                        else self.retry_delays[attempt]
                    )
                except ValueError:
                    delay = self.retry_delays[attempt]
                if delay > self.maximum_retry_after_seconds:
                    raise SemanticScholarRateLimitError(
                        f"Semantic Scholar requested waiting {delay:g}s"
                    ) from error
                self.sleep(max(0.0, delay))
        raise RuntimeError("Semantic Scholar retry loop ended unexpectedly")

    @staticmethod
    def _normalize(item: dict[str, Any]) -> dict[str, Any]:
        external = item.get("externalIds", {}) or {}
        doi = str(external.get("DOI", "") or "").strip().lower()
        pdf = item.get("openAccessPdf", {}) or {}
        paper_id = str(item.get("paperId", "") or "")
        return {
            "paper_id": f"semantic_scholar:{paper_id}",
            "semantic_scholar_id": paper_id,
            "title": str(item.get("title", "") or "").strip(),
            "abstract": str(item.get("abstract", "") or "").strip(),
            "year": item.get("year"),
            "journal": str(item.get("venue", "") or "").strip(),
            "doi": doi,
            "url": str(item.get("url", "") or ""),
            "citation_count": int(item.get("citationCount", 0) or 0),
            "is_open_access": bool(item.get("isOpenAccess", False)),
            "open_access_pdf_url": str(pdf.get("url", "") or ""),
            "external_ids": external,
            "source": "Semantic Scholar",
            "metadata_provider": "semantic_scholar",
        }

    def _cache_path(self, query: str, limit: int) -> Path:
        key = hashlib.sha256(
            json.dumps(
                {"query": query, "limit": limit}, sort_keys=True
            ).encode("utf-8")
        ).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.cache_ttl_seconds:
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            payload = value.get("payload", {})
            return payload if isinstance(payload, dict) else None
        except (OSError, json.JSONDecodeError):
            return None


__all__ = ["SemanticScholarClient", "SemanticScholarRateLimitError"]
