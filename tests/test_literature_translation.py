from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api.server import app
from app.domain.literature_translation import LiteratureTranslationService
from tools.llm_client import LLMError


class LiteratureTranslationServiceTest(unittest.TestCase):
    def test_doi_cache_key_is_normalized(self):
        first = LiteratureTranslationService.cache_key(
            doi="https://doi.org/10.1000/ABC ", title="First title"
        )
        second = LiteratureTranslationService.cache_key(
            doi="10.1000/abc", title="Different title"
        )
        self.assertEqual(first, second)

    def test_cache_hit_does_not_call_llm(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = Mock()
            client.chat_json.return_value = {
                "title_zh": "中文标题",
                "abstract_zh": "中文摘要",
            }
            service = LiteratureTranslationService(temporary, client=client)
            first = service.translate(
                doi="10.1000/test", title="English title", abstract="English abstract"
            )
            second = service.translate(
                doi="https://doi.org/10.1000/TEST",
                title="English title",
                abstract="English abstract",
            )
            self.assertEqual(first["translation_status"], "translated")
            self.assertEqual(second["translation_status"], "cached")
            self.assertTrue(second["translation_cached"])
            client.chat_json.assert_called_once()
            self.assertEqual(len(list(Path(temporary).glob("*.json"))), 1)

    def test_translation_failure_is_non_blocking(self):
        client = Mock()
        client.chat_json.side_effect = LLMError("temporary failure")
        with tempfile.TemporaryDirectory() as temporary:
            result = LiteratureTranslationService(temporary, client=client).translate(
                doi="", title="English title", abstract="English abstract"
            )
        self.assertEqual(result["translation_status"], "failed")
        self.assertEqual(result["title_en"], "English title")
        self.assertEqual(result["abstract_en"], "English abstract")
        self.assertEqual(result["title_zh"], "")


class LiteratureTranslationApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("app.api.server.literature_translation")
    def test_api_returns_only_safe_translation_fields(self, service):
        service.translate.return_value = {
            "title_en": "English title",
            "title_zh": "中文标题",
            "abstract_en": "English abstract",
            "abstract_zh": "中文摘要",
            "translation_status": "cached",
            "translation_source": "kimi_machine_translation",
            "translation_cached": True,
            "translation_error": "",
        }
        response = self.client.post(
            "/api/literature/translations",
            json={
                "doi": "10.1000/test",
                "title": "English title",
                "abstract": "English abstract",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["translation_status"], "cached")
        self.assertNotIn("cache_path", response.json())
        self.assertNotIn("api_key", response.json())


if __name__ == "__main__":
    unittest.main()
