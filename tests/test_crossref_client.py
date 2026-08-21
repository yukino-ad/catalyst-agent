import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from tools.literature.crossref_client import (
    CrossrefClient,
    CrossrefRateLimitError,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class CrossrefClientTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.client = CrossrefClient(
            cache_dir=root / "cache",
            raw_dir=root / "raw",
            minimum_interval_seconds=0,
            retry_delays=(0,),
            sleep=lambda _seconds: None,
        )

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def payload():
        return {"message": {"items": [
            {
                "DOI": "10.1000/TEST",
                "title": ["Five-metal HEA"],
                "abstract": "<jats:p>CuFeCoNiMn &amp; CO2RR.</jats:p>",
                "container-title": ["Catalysis Journal"],
                "issued": {"date-parts": [[2025, 1, 2]]},
                "type": "journal-article",
                "ISSN": ["1234-5678"],
            },
            {"title": ["No DOI must be ignored"]},
        ]}}

    def test_search_requires_doi_and_cleans_jats_abstract(self):
        with patch(
            "urllib.request.urlopen", return_value=_Response(self.payload())
        ):
            records = self.client.search("five metal hea", per_page=5)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].doi, "10.1000/test")
        self.assertEqual(records[0].abstract, "CuFeCoNiMn & CO2RR.")
        self.assertTrue(records[0].metadata_verified)
        self.assertTrue(records[0].claim_evidence_available)

    def test_cache_prevents_second_network_request(self):
        with patch(
            "urllib.request.urlopen", return_value=_Response(self.payload())
        ) as urlopen:
            self.client.search("cached query", per_page=5)
            self.client.search("cached query", per_page=5)
        self.assertEqual(urlopen.call_count, 1)

    def test_invalid_mailto_is_rejected_before_network(self):
        with self.assertRaisesRegex(ValueError, "CROSSREF_MAILTO"):
            self.client.search("query", mailto="invalid-address")

    def test_excessive_retry_after_aborts(self):
        error = urllib.error.HTTPError(
            "https://api.crossref.org/works",
            429,
            "rate limited",
            {"Retry-After": "3600"},
            None,
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(CrossrefRateLimitError):
                self.client.search("rate limited query")


if __name__ == "__main__":
    unittest.main()
