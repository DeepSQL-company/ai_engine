import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatSession:
    messages: list[dict[str, Any]] = field(default_factory=list)


class ChatStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._lock = threading.Lock()

    def get_or_create(self, chat_id: str | None = None) -> tuple[str, ChatSession, bool]:
        with self._lock:
            if chat_id and chat_id in self._sessions:
                return chat_id, self._sessions[chat_id], False

            resolved_chat_id = chat_id or str(uuid.uuid4())
            session = ChatSession()
            self._sessions[resolved_chat_id] = session
            return resolved_chat_id, session, True

    def append_user_message(self, chat_id: str, content: str) -> None:
        with self._lock:
            session = self._sessions[chat_id]
            session.messages.append({"role": "user", "content": content})

    def get_messages(self, chat_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._sessions[chat_id].messages)


chat_store = ChatStore()
