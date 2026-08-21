import json
import tempfile
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from tools.literature.openalex_client import (
    OpenAlexClient,
    OpenAlexRateLimitError,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class OpenAlexRateLimitTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.sleeps = []
        self.client = OpenAlexClient(
            raw_dir=root / "raw",
            cache_dir=root / "cache",
            minimum_interval_seconds=0,
            retry_delays=(1, 2, 3),
            sleep=self.sleeps.append,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_429_retries_then_succeeds(self):
        error = urllib.error.HTTPError(
            "https://example.test", 429, "rate limited", {}, BytesIO()
        )
        payload = {"results": [{"id": "https://openalex.org/W1", "title": "Paper"}]}
        with patch("urllib.request.urlopen", side_effect=[error, Response(payload)]) as call:
            records = self.client.search("query", 5)
        self.assertEqual(len(records), 1)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(self.sleeps, [1])

    def test_query_cache_avoids_second_request(self):
        payload = {"results": [{"id": "https://openalex.org/W1", "title": "Paper"}]}
        with patch("urllib.request.urlopen", return_value=Response(payload)) as call:
            self.client.search("same query", 5)
            self.client.search("same query", 5)
        self.assertEqual(call.call_count, 1)

    def test_excessive_retry_after_fails_without_sleeping(self):
        error = urllib.error.HTTPError(
            "https://example.test",
            429,
            "rate limited",
            {"Retry-After": "35858"},
            BytesIO(),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(OpenAlexRateLimitError):
                self.client.search("long rate limit", 5)
        self.assertEqual(self.sleeps, [])

    def test_non_ascii_mailto_is_rejected_before_request(self):
        with patch("urllib.request.urlopen") as call:
            with self.assertRaisesRegex(ValueError, "ASCII email"):
                self.client.search("query", 5, "替换为真实邮箱")
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
