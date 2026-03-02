import uuid
from collections import deque
from threading import Lock

from app.web.schemas import ChatTurn


class InMemorySessionStore:
    """Small bounded chat memory per session for basic multi-turn context."""

    def __init__(self, max_turn_pairs: int = 8) -> None:
        self._max_turn_pairs = max(1, max_turn_pairs)
        self._sessions: dict[str, deque[ChatTurn]] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str | None) -> str:
        with self._lock:
            sid = (session_id or "").strip() or uuid.uuid4().hex[:12]
            if sid not in self._sessions:
                # 2 entries per turn pair: user + assistant
                self._sessions[sid] = deque(maxlen=self._max_turn_pairs * 2)
            return sid

    def append(self, session_id: str, role: str, content: str) -> None:
        with self._lock:
            queue = self._sessions.setdefault(
                session_id, deque(maxlen=self._max_turn_pairs * 2)
            )
            queue.append(ChatTurn(role=role, content=content))

    def history(self, session_id: str) -> list[ChatTurn]:
        with self._lock:
            turns = self._sessions.get(session_id)
            if not turns:
                return []
            return list(turns)

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
