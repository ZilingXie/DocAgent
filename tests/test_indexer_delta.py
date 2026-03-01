import unittest

from app.ingest.indexer import _compute_doc_delta


class IndexerDeltaTests(unittest.TestCase):
    def test_compute_doc_delta(self) -> None:
        existing = {
            "doc-a": "h1",
            "doc-b": "h2",
            "doc-c": "h3",
        }
        new = {
            "doc-a": "h1",      # unchanged
            "doc-b": "h2-new",  # changed
            "doc-d": "h4",      # added
        }
        changed, removed, unchanged = _compute_doc_delta(existing, new)
        self.assertEqual(changed, ["doc-b", "doc-d"])
        self.assertEqual(removed, ["doc-c"])
        self.assertEqual(unchanged, ["doc-a"])


if __name__ == "__main__":
    unittest.main()

