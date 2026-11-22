import io
import unittest
from contextlib import redirect_stdout

import contribution_examples


class BundledExampleTests(unittest.TestCase):
    def test_bundled_chain_and_legacy_fixtures(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            contribution_examples.main()
        output = buffer.getvalue()
        self.assertIn('V1_SAME_BYTES_ERASED_SOURCE', output)
        self.assertIn('V1_LEGACY_AND_COMMIT_FIXTURES_OK', output)
