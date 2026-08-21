from __future__ import annotations

import hashlib
import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tools.literature.schemas import PaperRecord


class CrossrefRateLimitError(OSError):
    """Crossref requested a delay unsuitable for an interactive run."""

    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            "Crossref rate limit requires waiting "
            f"{retry_after_seconds:g}s; interactive retry aborted."
        )


class CrossrefClient:
    """Search and verify DOI metadata through the public Crossref API."""

    _request_lock = threading.Lock()
    _last_request_at = 0.0

    def __init__(
        self,
        cache_dir: str | Path = "database/literature/cache/crossref",
        raw_dir: str | Path = "database/literature/raw/crossref",
        timeout_seconds: int = 30,
        minimum_interval_seconds: float = 1.0,
        cache_ttl_seconds: int = 86400,
        retry_delays: tuple[float, ...] = (3.0, 10.0, 30.0),
        maximum_retry_after_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        root = Path(__file__).resolve().parents[2]
        self.cache_dir = self._directory(cache_dir, root)
        self.raw_dir = self._directory(raw_dir, root)
        self.timeout_seconds = timeout_seconds
        self.minimum_interval_seconds = minimum_interval_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.retry_delays = retry_delays
        self.maximum_retry_after_seconds = maximum_retry_after_seconds
        self.sleep = sleep
        self.clock = clock

    @staticmethod
    def _directory(value: str | Path, root: Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def search(
        self,
        query: str,
        per_page: int = 20,
        mailto: str = "",
    ) -> list[PaperRecord]:
        if not 1 <= per_page <= 100:
            raise ValueError("per_page must be between 1 and 100")
        query = query.strip()
        if not query:
            raise ValueError("Crossref query must not be empty")
        if mailto and (not mailto.isascii() or "@" not in mailto):
            raise ValueError("CROSSREF_MAILTO must be an ASCII email address or empty")

        cache_path = self._cache_path(query, per_page)
        payload = self._read_cache(cache_path)
        if payload is None:
            payload = self._request(query, per_page, mailto)
            wrapped = {
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
            }
            cache_path.write_text(
                json.dumps(wrapped, ensure_ascii=False), encoding="utf-8"
            )
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            (self.raw_dir / f"search_{timestamp}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        items = payload.get("message", {}).get("items", [])
        return [
            self._to_record(item)
            for item in items
            if isinstance(item, dict) and item.get("DOI") and item.get("title")
        ]

    def _request(self, query: str, rows: int, mailto: str) -> dict[str, Any]:
        parameters = {
            "query.bibliographic": query,
            "rows": str(rows),
            "filter": "type:journal-article",
        }
        if mailto:
            parameters["mailto"] = mailto
        url = "https://api.crossref.org/works?" + urllib.parse.urlencode(parameters)
        user_agent = "catalyst-agent/0.5"
        if mailto:
            user_agent += f" (mailto:{mailto})"

        for attempt in range(len(self.retry_delays) + 1):
            self._throttle()
            request = urllib.request.Request(
                url,
                headers={"User-Agent": user_agent, "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_seconds
                ) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                if error.code != 429 or attempt >= len(self.retry_delays):
                    raise
                delay = self._retry_after(error, self.retry_delays[attempt])
                if delay > self.maximum_retry_after_seconds:
                    raise CrossrefRateLimitError(delay) from error
                print(
                    f"[B4] Crossref rate limited; retrying in {delay:g}s "
                    f"({attempt + 1}/{len(self.retry_delays)}).",
                    flush=True,
                )
                self.sleep(delay)
        raise RuntimeError("Crossref retry loop ended unexpectedly")

    def _throttle(self) -> None:
        with self._request_lock:
            elapsed = self.clock() - type(self)._last_request_at
            delay = max(0.0, self.minimum_interval_seconds - elapsed)
            if delay:
                self.sleep(delay)
            type(self)._last_request_at = self.clock()

    @staticmethod
    def _retry_after(error: urllib.error.HTTPError, fallback: float) -> float:
        value = error.headers.get("Retry-After") if error.headers else None
        try:
            return max(0.0, float(value)) if value is not None else fallback
        except ValueError:
            return fallback

    def _cache_path(self, query: str, rows: int) -> Path:
        key = hashlib.sha256(
            json.dumps(
                {"query": query, "rows": rows}, sort_keys=True
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

    @classmethod
    def _to_record(cls, item: dict[str, Any]) -> PaperRecord:
        doi = str(item.get("DOI", "") or "").strip().lower()
        title = cls._first(item.get("title"))
        abstract = cls._plain_text(item.get("abstract", ""))
        journal = cls._first(item.get("container-title"))
        year = cls._year(item)
        issns = [str(value) for value in item.get("ISSN", []) if str(value)]
        return PaperRecord(
            paper_id=f"crossref:{doi}",
            title=title,
            abstract=abstract,
            year=year,
            journal=journal,
            doi=doi,
            url=str(item.get("URL", "") or f"https://doi.org/{doi}"),
            source="Crossref",
            publication_type=str(item.get("type", "") or "journal-article"),
            issns=issns,
            metadata_verified=True,
            metadata_provider="crossref",
            claim_evidence_available=bool(abstract),
        )

    @staticmethod
    def _first(value: Any) -> str:
        if isinstance(value, list) and value:
            return str(value[0] or "").strip()
        return str(value or "").strip()

    @staticmethod
    def _plain_text(value: Any) -> str:
        text = html.unescape(str(value or ""))
        text = re.sub(r"<[^>]+>", " ", text)
        return " ".join(text.split())

    @staticmethod
    def _year(item: dict[str, Any]) -> int | None:
        for field in ("published-print", "published-online", "published", "issued"):
            parts = item.get(field, {}).get("date-parts", [])
            if parts and parts[0]:
                try:
                    return int(parts[0][0])
                except (TypeError, ValueError):
                    pass
        return None
