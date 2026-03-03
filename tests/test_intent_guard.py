import unittest

from app.web.intent import (
    INSUFFICIENT_EVIDENCE_REPLY,
    is_obviously_out_of_scope,
    looks_agora_related,
    should_replace_insufficient_reply,
)


class IntentGuardTests(unittest.TestCase):
    def test_out_of_scope_weather(self) -> None:
        self.assertTrue(is_obviously_out_of_scope("How is the weather today?"))

    def test_agora_related_query(self) -> None:
        self.assertTrue(looks_agora_related("How do I join channel with Agora token?"))
        self.assertFalse(is_obviously_out_of_scope("How do I join channel with Agora token?"))

    def test_replace_insufficient_for_unrelated_first_turn(self) -> None:
        self.assertTrue(
            should_replace_insufficient_reply(
                question="Tell me a joke",
                answer_text=INSUFFICIENT_EVIDENCE_REPLY,
                has_history=False,
            )
        )

    def test_do_not_replace_insufficient_for_follow_up(self) -> None:
        self.assertFalse(
            should_replace_insufficient_reply(
                question="What about that?",
                answer_text=INSUFFICIENT_EVIDENCE_REPLY,
                has_history=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
