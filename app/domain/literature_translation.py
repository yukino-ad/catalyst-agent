from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools.llm_client import LLMError, OpenAICompatibleClient


class LiteratureTranslationService:
    """Translate source metadata without changing the authoritative English text."""

    def __init__(
        self,
        cache_root: str | Path | None = None,
        client: OpenAICompatibleClient | None = None,
    ) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.cache_root = Path(
            cache_root or project_root / "data" / "literature_translation_cache"
        )
        self.client = client

    def translate(self, *, doi: str, title: str, abstract: str) -> dict[str, Any]:
        title_en = str(title).strip()
        abstract_en = str(abstract).strip()
        cache_key = self.cache_key(doi=doi, title=title_en)
        base = {
            "title_en": title_en,
            "abstract_en": abstract_en,
            "translation_source": "kimi_machine_translation",
            "translation_cached": False,
            "translation_error": "",
        }
        if not title_en and not abstract_en:
            return {
                **base,
                "title_zh": "",
                "abstract_zh": "",
                "translation_status": "unavailable",
            }

        cached = self._read_cache(cache_key)
        if cached is not None:
            return {
                **base,
                "title_zh": str(cached.get("title_zh", "")),
                "abstract_zh": str(cached.get("abstract_zh", "")),
                "translation_status": "cached",
                "translation_cached": True,
            }

        try:
            client = self.client or OpenAICompatibleClient()
            translated = client.chat_json(
                [
                    {
                        "role": "system",
                        "content": (
                            "You translate academic catalyst literature into Simplified Chinese. "
                            "Return one JSON object with title_zh and abstract_zh only. Preserve "
                            "chemical formulas, alloy compositions, DOI values, numbers, symbols, "
                            "and units exactly. Do not add, infer, summarize, or strengthen claims."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"title_en": title_en, "abstract_en": abstract_en},
                            ensure_ascii=False,
                        ),
                    },
                ],
                max_tokens=8192,
                timeout_seconds=180,
            )
            title_zh = self._translated_text(translated.get("title_zh"), 2000)
            abstract_zh = self._translated_text(translated.get("abstract_zh"), 12000)
            if title_en and not title_zh:
                raise LLMError("Translation response omitted title_zh")
            if abstract_en and not abstract_zh:
                raise LLMError("Translation response omitted abstract_zh")
            payload = {"title_zh": title_zh, "abstract_zh": abstract_zh}
            self._write_cache(cache_key, payload)
            return {
                **base,
                **payload,
                "translation_status": "translated",
            }
        except (LLMError, OSError, ValueError, TypeError) as error:
            return {
                **base,
                "title_zh": "",
                "abstract_zh": "",
                "translation_status": "failed",
                "translation_error": self._safe_error(error),
            }

    @staticmethod
    def cache_key(*, doi: str, title: str) -> str:
        normalized_doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi.strip().lower())
        normalized_doi = re.sub(r"\s+", "", normalized_doi)
        if normalized_doi:
            identity = f"doi:{normalized_doi}"
        else:
            normalized_title = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
            identity = f"title:{normalized_title}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        path = self.cache_root / f"{cache_key}.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _write_cache(self, cache_key: str, payload: dict[str, str]) -> None:
        self.cache_root.mkdir(parents=True, exist_ok=True)
        target = self.cache_root / f"{cache_key}.json"
        temporary = self.cache_root / f".{cache_key}.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)

    @staticmethod
    def _translated_text(value: Any, limit: int) -> str:
        return str(value or "").strip()[:limit]

    @staticmethod
    def _safe_error(error: Exception) -> str:
        message = re.sub(r"(?:sk-|Bearer\s+)[A-Za-z0-9._-]+", "[redacted]", str(error))
        return message[:500]
