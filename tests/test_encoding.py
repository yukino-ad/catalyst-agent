import io
import os
import unittest
from unittest.mock import patch

from app.encoding import configure_utf8_stdio


class EncodingTest(unittest.TestCase):
    def test_utf8_configuration_sets_process_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            configure_utf8_stdio()

            self.assertEqual(os.environ["PYTHONUTF8"], "1")
            self.assertEqual(os.environ["PYTHONIOENCODING"], "utf-8")

    def test_non_reconfigurable_stream_is_ignored(self):
        stream = io.StringIO()
        stream.reconfigure = None

        with patch("app.encoding.sys.stdout", stream):
            configure_utf8_stdio()


if __name__ == "__main__":
    unittest.main()
