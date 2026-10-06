"""Temporary, in-memory conversation sessions.

Nothing here is written to disk. A session disappears when it is ended, when it
sits idle past the configured limit, or when the server stops.
"""
import threading
import time
import uuid
from dataclasses import dataclass, field


class SessionNotFound(Exception):
    """Raised for missing sessions and for sessions owned by someone else.

    Both cases look identical to the caller, so session IDs can't be probed.
    """


@dataclass
class Message:
    id: str
    role: str  # "user" or "assistant"
    content: str
    demo: bool = False

    def public(self) -> dict:
        return {"id": self.id, "role": self.role, "content": self.content, "demo": self.demo}


@dataclass
class Session:
    id: str
    owner: str
    companion_id: str
    messages: list = field(default_factory=list)
    last_active: float = field(default_factory=time.time)
    busy: bool = False
    # client_message_id -> finished response, so a retried send never creates a second reply.
    completed: dict = field(default_factory=dict)
    # assistant message id -> generated audio bytes, so retries/replays don't pay twice.
    audio: dict = field(default_factory=dict)

    @property
    def user_turns(self) -> int:
        return sum(1 for m in self.messages if m.role == "user")

    def find_message(self, message_id: str):
        return next((m for m in self.messages if m.id == message_id), None)


class SessionStore:
    def __init__(self, idle_minutes: int, max_sessions: int):
        self._sessions: dict = {}
        self._lock = threading.Lock()
        self.idle_seconds = idle_minutes * 60
        self.max_sessions = max_sessions

    def _purge(self) -> None:
        cutoff = time.time() - self.idle_seconds
        for sid in [s.id for s in self._sessions.values() if s.last_active < cutoff and not s.busy]:
            del self._sessions[sid]

    def create(self, owner: str, companion_id: str, opening: str) -> Session:
        with self._lock:
            self._purge()
            if len(self._sessions) >= self.max_sessions:
                raise OverflowError("too many active sessions")
            session = Session(id=uuid.uuid4().hex, owner=owner, companion_id=companion_id)
            session.messages.append(Message(id=uuid.uuid4().hex, role="assistant", content=opening))
            self._sessions[session.id] = session
            return session

    def get(self, owner: str, session_id: str) -> Session:
        with self._lock:
            self._purge()
            session = self._sessions.get(session_id)
            if session is None or session.owner != owner:
                raise SessionNotFound()
            session.last_active = time.time()
            return session

    def exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions

    def end(self, owner: str, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.owner != owner:
                raise SessionNotFound()
            del self._sessions[session_id]

    def try_lock(self, session: Session) -> bool:
        with self._lock:
            if session.busy:
                return False
            session.busy = True
            return True

    def unlock(self, session: Session) -> None:
        with self._lock:
            session.busy = False
