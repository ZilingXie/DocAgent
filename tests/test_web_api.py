import unittest
from unittest.mock import patch
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.models import Citation, QAResult, RetrievedChunk
from app.web.intent import OUT_OF_SCOPE_REPLY
from app.web.main import create_app
from app.qa.messages import INSUFFICIENT_EVIDENCE_REPLY


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


def _insufficient_result() -> QAResult:
    return QAResult(
        answer_text=INSUFFICIENT_EVIDENCE_REPLY,
        citations=[],
        used_chunks=[],
        latency_ms=45,
    )


class WebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_index_page(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="chat-root"', response.text)

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

    @patch("app.web.main.run_answer")
    def test_chat_out_of_scope_short_circuit(self, mock_answer) -> None:
        response = self.client.post("/api/chat", json={"message": "How is the weather today?"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["answer_text"], OUT_OF_SCOPE_REPLY)
        self.assertEqual(body["citations"], [])
        self.assertEqual(len(body["history"]), 2)
        mock_answer.assert_not_called()

    @patch("app.web.main.run_answer")
    def test_ask_out_of_scope_short_circuit(self, mock_answer) -> None:
        response = self.client.post("/api/ask", json={"question": "今天天气怎么样"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["answer_text"], OUT_OF_SCOPE_REPLY)
        self.assertEqual(body["citations"], [])
        mock_answer.assert_not_called()

    @patch("app.web.main.run_answer")
    def test_ask_replace_insufficient_reply_for_unrelated_question(self, mock_answer) -> None:
        mock_answer.return_value = _insufficient_result()
        response = self.client.post("/api/ask", json={"question": "Tell me a joke"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["answer_text"], OUT_OF_SCOPE_REPLY)
        self.assertEqual(body["citations"], [])

    @patch("app.web.main.run_answer")
    def test_chat_keep_insufficient_for_follow_up_question(self, mock_answer) -> None:
        mock_answer.side_effect = [_fake_result("chat answer"), _insufficient_result()]
        first = self.client.post("/api/chat", json={"message": "How to join channel with Agora?"})
        self.assertEqual(first.status_code, 200)
        session_id = first.json()["session_id"]

        second = self.client.post(
            "/api/chat",
            json={"message": "What about that?", "session_id": session_id},
        )
        self.assertEqual(second.status_code, 200)
        body = second.json()
        self.assertEqual(body["answer_text"], INSUFFICIENT_EVIDENCE_REPLY)

    def test_docs_file_and_path_safety(self) -> None:
        source_file = "video-calling_overview.md"
        response = self.client.get(f"/docs/{quote(source_file, safe='/')}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/markdown", response.headers.get("content-type", ""))

        traversal = self.client.get("/docs/%2e%2e/%2e%2e/etc/passwd")
        self.assertEqual(traversal.status_code, 400)


if __name__ == "__main__":
    unittest.main()
