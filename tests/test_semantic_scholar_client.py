import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.literature.semantic_scholar_client import SemanticScholarClient


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class SemanticScholarClientTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.client = SemanticScholarClient(
            cache_dir=root / "cache",
            raw_dir=root / "raw",
            retry_delays=(0,),
            sleep=lambda _seconds: None,
        )

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def payload():
        return {"data": [{
            "paperId": "S2ID",
            "title": "CuFeCoNiMn HEA for CO2RR",
            "abstract": "Explicit abstract.",
            "year": 2025,
            "venue": "Catalysis Journal",
            "url": "https://www.semanticscholar.org/paper/S2ID",
            "externalIds": {"DOI": "10.1000/TEST"},
            "citationCount": 12,
            "isOpenAccess": True,
            "openAccessPdf": {"url": "https://example.org/paper.pdf"},
        }]}

    def test_search_normalizes_traceable_metadata(self):
        with patch(
            "urllib.request.urlopen", return_value=_Response(self.payload())
        ):
            result = self.client.search("hea co2rr", limit=5)
        paper = result["papers"][0]
        self.assertEqual(paper["doi"], "10.1000/test")
        self.assertEqual(paper["semantic_scholar_id"], "S2ID")
        self.assertEqual(paper["citation_count"], 12)

    def test_cache_prevents_second_request(self):
        with patch(
            "urllib.request.urlopen", return_value=_Response(self.payload())
        ) as request:
            self.client.search("cached semantic query", limit=5)
            self.client.search("cached semantic query", limit=5)
        self.assertEqual(request.call_count, 1)

    def test_find_by_doi_requires_exact_match(self):
        with patch(
            "urllib.request.urlopen", return_value=_Response(self.payload())
        ):
            paper = self.client.find_by_doi(
                "https://doi.org/10.1000/TEST"
            )
        self.assertIsNotNone(paper)
        self.assertEqual(paper["semantic_scholar_id"], "S2ID")


if __name__ == "__main__":
    unittest.main()
