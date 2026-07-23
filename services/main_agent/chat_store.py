import threading
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from services.main_agent.models import RestoreContext


class SessionDisposition(StrEnum):
    NEW = "new"
    EXISTING = "existing"
    RESTORED = "restored"


class ChatContextMissingError(Exception):
    pass


@dataclass
class ChatSession:
    messages: list[dict[str, Any]] = field(default_factory=list)
    conversation_summary: str = ""
    context_revision: int = 0
    latest_included_turn_id: str | None = None


class ChatStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._lock = threading.Lock()

    def get_or_restore(
        self,
        chat_id: str | None = None,
        restore_context: RestoreContext | None = None,
    ) -> tuple[str, ChatSession, SessionDisposition]:
        with self._lock:
            if chat_id and chat_id in self._sessions:
                session = self._sessions[chat_id]
                if restore_context is not None:
                    session.context_revision = restore_context.revision
                    session.conversation_summary = restore_context.summary
                    session.latest_included_turn_id = (
                        str(restore_context.latest_included_turn_id)
                        if restore_context.latest_included_turn_id
                        else None
                    )
                return chat_id, session, SessionDisposition.EXISTING

            if chat_id and restore_context is None:
                raise ChatContextMissingError("chat_context_missing")

            resolved_chat_id = chat_id or str(uuid.uuid4())
            if restore_context is None:
                session = ChatSession()
                disposition = SessionDisposition.NEW
            else:
                session = ChatSession(
                    messages=[
                        message.model_dump(exclude_none=True)
                        for message in restore_context.messages
                    ],
                    conversation_summary=restore_context.summary,
                    context_revision=restore_context.revision,
                    latest_included_turn_id=(
                        str(restore_context.latest_included_turn_id)
                        if restore_context.latest_included_turn_id
                        else None
                    ),
                )
                disposition = SessionDisposition.RESTORED
            self._sessions[resolved_chat_id] = session
            return resolved_chat_id, session, disposition

    def get_or_create(self, chat_id: str | None = None) -> tuple[str, ChatSession, bool]:
        resolved, session, disposition = self.get_or_restore(chat_id)
        return resolved, session, disposition == SessionDisposition.NEW

    def append_user_message(self, chat_id: str, content: str) -> None:
        with self._lock:
            session = self._sessions[chat_id]
            session.messages.append({"role": "user", "content": content})

    def get_messages(self, chat_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._sessions[chat_id].messages)


chat_store = ChatStore()
