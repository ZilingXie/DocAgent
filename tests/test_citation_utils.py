import unittest

from app.models import RetrievedChunk
from app.utils.citation import citations_from_chunk_ids, heading_from_chunk


class CitationUtilsTests(unittest.TestCase):
    def test_heading_from_chunk(self) -> None:
        chunk = RetrievedChunk(
            chunk_id="a-1",
            text="x",
            score=0.1,
            source_path="doc/a.md",
            h1="Quickstart",
            h2="Join channel",
            h3="Android",
        )
        self.assertEqual(heading_from_chunk(chunk), "Quickstart > Join channel > Android")

    def test_citations_from_chunk_ids_filters_unknown_ids(self) -> None:
        chunks = [
            RetrievedChunk(chunk_id="a-1", text="x", score=0.1, source_path="doc/a.md", h1="A"),
            RetrievedChunk(chunk_id="b-1", text="y", score=0.2, source_path="doc/b.md", h1="B"),
        ]
        citations = citations_from_chunk_ids(["a-1", "z-9", "b-1"], chunks)
        self.assertEqual(len(citations), 2)
        self.assertEqual(citations[0].chunk_id, "a-1")
        self.assertEqual(citations[1].chunk_id, "b-1")


if __name__ == "__main__":
    unittest.main()

