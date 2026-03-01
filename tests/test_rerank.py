import unittest

from app.models import RetrievedChunk
from app.retrieval.rerank import rerank


class RerankTests(unittest.TestCase):
    def test_rerank_prefers_query_overlap(self) -> None:
        query = "join channel android"
        chunks = [
            RetrievedChunk(
                chunk_id="c1",
                text="This section explains how to join channel on Android.",
                score=0.05,
                source_path="doc/one.md",
                h1="Quickstart",
                h2="Join channel",
            ),
            RetrievedChunk(
                chunk_id="c2",
                text="Billing policy and subscription package details.",
                score=0.20,
                source_path="doc/two.md",
                h1="Billing",
            ),
        ]
        ranked = rerank(query=query, chunks=chunks, top_n=1)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].chunk_id, "c1")


if __name__ == "__main__":
    unittest.main()

