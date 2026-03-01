import tempfile
import unittest
from pathlib import Path

from app.eval.runner import load_questions, run_evaluation
from app.models import Citation, QAResult, RetrievedChunk


class EvalRunnerTests(unittest.TestCase):
    def test_load_questions_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dataset = Path(td) / "q.jsonl"
            dataset.write_text(
                '{"question":"q1"}\n{"q":"q2"}\n',
                encoding="utf-8",
            )
            questions = load_questions(dataset)
            self.assertEqual(questions, ["q1", "q2"])

    def test_load_questions_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dataset = Path(td) / "q.jsonl"
            dataset.write_text('{"question":"ok"}\nnot-json\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_questions(dataset)

    def test_run_evaluation_summary_and_thresholds(self) -> None:
        chunks = [RetrievedChunk(chunk_id="c1", text="x", score=1.0, source_path="doc/a.md")]
        citations = [Citation(source_path="doc/a.md", heading="h", chunk_id="c1")]

        responses = {
            "q1": QAResult(answer_text="a1", citations=citations, used_chunks=chunks, latency_ms=100),
            "q2": QAResult(
                answer_text="Not enough evidence in provided docs.",
                citations=[],
                used_chunks=[],
                latency_ms=120,
            ),
        }

        def fake_answer(q: str) -> QAResult:
            return responses[q]

        summary = run_evaluation(["q1", "q2"], answer_fn=fake_answer)
        self.assertEqual(summary.total, 2)
        self.assertEqual(summary.answered, 1)
        self.assertEqual(summary.insufficient, 1)
        self.assertEqual(summary.with_citations, 1)
        self.assertAlmostEqual(summary.avg_latency_ms, 110.0, places=1)
        self.assertAlmostEqual(summary.citation_presence, 0.5, places=3)
        self.assertTrue(
            summary.passes(
                min_citation_presence=0.5,
                max_avg_latency_ms=150.0,
                max_insufficient_rate=0.6,
            )
        )
        self.assertFalse(
            summary.passes(
                min_citation_presence=1.0,
                max_avg_latency_ms=150.0,
                max_insufficient_rate=0.6,
            )
        )


if __name__ == "__main__":
    unittest.main()

