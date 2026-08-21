from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tools.literature.schemas import PaperRecord


class OpenAlexRateLimitError(OSError):
    """OpenAlex asked the client to wait longer than an interactive run allows."""

    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            "OpenAlex rate limit requires waiting "
            f"{retry_after_seconds:g}s; interactive retry aborted."
        )


def restore_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    if not inverted_index:
        return ""
    positioned = [
        (position, word)
        for word, positions in inverted_index.items()
        for position in positions
    ]
    return " ".join(word for _, word in sorted(positioned))


class OpenAlexClient:
    """Rate-limited OpenAlex client with bounded retries and query caching."""

    _request_lock = threading.Lock()
    _last_request_at = 0.0

    def __init__(
        self,
        raw_dir: str | Path = "database/literature/raw/openalex",
        cache_dir: str | Path = "database/literature/cache/openalex",
        timeout_seconds: int = 30,
        minimum_interval_seconds: float = 1.5,
        cache_ttl_seconds: int = 86400,
        retry_delays: tuple[float, ...] = (5.0, 15.0, 30.0),
        maximum_retry_after_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.raw_dir = self._directory(raw_dir, project_root)
        self.cache_dir = self._directory(cache_dir, project_root)
        self.timeout_seconds = timeout_seconds
        self.minimum_interval_seconds = minimum_interval_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.retry_delays = retry_delays
        self.maximum_retry_after_seconds = maximum_retry_after_seconds
        self.sleep = sleep
        self.clock = clock

    @staticmethod
    def _directory(value: str | Path, project_root: Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = project_root / path
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
            raise ValueError("OpenAlex query must not be empty")

        cache_path = self._cache_path(query, per_page)
        payload = self._read_cache(cache_path)
        if payload is None:
            payload = self._request(query, per_page, mailto)
            cache_path.write_text(
                json.dumps({
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                    "payload": payload,
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            (self.raw_dir / f"search_{timestamp}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return [
            self._to_record(item)
            for item in payload.get("results", [])
            if item.get("title")
        ]

    def _request(self, query: str, per_page: int, mailto: str) -> dict[str, Any]:
        parameters = {
            "search": query,
            "per-page": str(per_page),
            "select": (
                "id,title,publication_year,doi,primary_location,"
                "abstract_inverted_index,type,is_retracted"
            ),
        }
        if mailto:
            if not mailto.isascii() or "@" not in mailto:
                raise ValueError(
                    "OPENALEX_MAILTO must be an ASCII email address or empty."
                )
            parameters["mailto"] = mailto
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(parameters)
        user_agent = "catalyst-agent/0.4"
        if mailto:
            user_agent += f" (mailto:{mailto})"

        attempts = len(self.retry_delays) + 1
        for attempt in range(attempts):
            self._throttle()
            request = urllib.request.Request(url, headers={"User-Agent": user_agent})
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
                    raise OpenAlexRateLimitError(delay) from error
                print(
                    f"[B4] OpenAlex rate limited (429); retrying in {delay:g}s "
                    f"({attempt + 1}/{len(self.retry_delays)}).",
                    flush=True,
                )
                self.sleep(delay)
        raise RuntimeError("OpenAlex request retry loop ended unexpectedly")

    def _throttle(self) -> None:
        with self._request_lock:
            now = self.clock()
            elapsed = now - type(self)._last_request_at
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

    def _cache_path(self, query: str, per_page: int) -> Path:
        key = hashlib.sha256(
            json.dumps(
                {"query": query, "per_page": per_page},
                ensure_ascii=False,
                sort_keys=True,
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

    @staticmethod
    def _to_record(item: dict[str, Any]) -> PaperRecord:
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        openalex_id = str(item.get("id", "")).rsplit("/", 1)[-1]
        return PaperRecord(
            paper_id=f"openalex:{openalex_id}",
            title=item.get("title", ""),
            abstract=restore_abstract(item.get("abstract_inverted_index")),
            year=item.get("publication_year"),
            journal=source.get("display_name", ""),
            doi=item.get("doi") or "",
            url=(
                location.get("landing_page_url")
                or item.get("doi")
                or item.get("id", "")
            ),
            source="OpenAlex",
            publication_type=str(item.get("type", "") or ""),
            is_retracted=(item.get("is_retracted", False) is True),
            openalex_source_id=str(source.get("id", "") or "").rsplit("/", 1)[-1],
            issn_l=str(source.get("issn_l", "") or ""),
            issns=[str(value) for value in source.get("issn", []) if str(value)],
        )
