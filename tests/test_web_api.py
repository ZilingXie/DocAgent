import unittest
from unittest.mock import patch
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.models import Citation, QAResult, RetrievedChunk
from app.web.main import create_app


def _fake_result(answer_text: str = "sample answer") -> QAResult:
    chunk = RetrievedChunk(
        chunk_id="chunk-1",
        text="Sample text",
        score=1.0,
        source_path="doc/sample.md",
        h1="Sample",
    )
    citation = Citation(
        source_path="doc/sample.md",
        heading="Sample > Heading",
        chunk_id="chunk-1",
        source_url="https://docs.agora.io/en/video-calling/get-started/get-started-sdk?platform=android",
    )
    return QAResult(
        answer_text=answer_text,
        citations=[citation],
        used_chunks=[chunk],
        latency_ms=123,
    )


class WebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_index_page(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Start the conversation by sending a message.", response.text)

    def test_health(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(payload["status"], {"ok", "degraded"})
        self.assertIn("chroma_collection", payload)

    @patch("app.web.main.run_answer")
    def test_ask(self, mock_answer) -> None:
        mock_answer.return_value = _fake_result("ask answer")
        response = self.client.post("/api/ask", json={"question": "hello"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["answer_text"], "ask answer")
        self.assertEqual(payload["latency_ms"], 123)
        self.assertEqual(len(payload["citations"]), 1)
        self.assertTrue(
            payload["citations"][0]["source_link"].startswith("https://docs.agora.io/")
        )

    @patch("app.web.main.run_answer")
    def test_chat_session_history(self, mock_answer) -> None:
        mock_answer.return_value = _fake_result("chat answer")

        first = self.client.post("/api/chat", json={"message": "first question"})
        self.assertEqual(first.status_code, 200)
        first_body = first.json()
        session_id = first_body["session_id"]
        self.assertTrue(session_id)
        self.assertEqual(len(first_body["history"]), 2)

        second = self.client.post(
            "/api/chat",
            json={"message": "second question", "session_id": session_id},
        )
        self.assertEqual(second.status_code, 200)
        second_body = second.json()
        self.assertEqual(second_body["session_id"], session_id)
        self.assertEqual(len(second_body["history"]), 4)
        self.assertIn("Conversation memory:", mock_answer.call_args_list[1].args[0])

    def test_docs_file_and_path_safety(self) -> None:
        source_file = "video-calling_overview.md"
        response = self.client.get(f"/docs/{quote(source_file, safe='/')}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/markdown", response.headers.get("content-type", ""))

        traversal = self.client.get("/docs/%2e%2e/%2e%2e/etc/passwd")
        self.assertEqual(traversal.status_code, 400)


if __name__ == "__main__":
    unittest.main()
