import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from services.main_agent.chat_store import (
    ChatContextMissingError,
    ChatStore,
    SessionDisposition,
)
from services.main_agent.context import (
    canonicalize_turn_messages,
    compact_conversation_if_needed,
    compact_tool_result,
)
from services.main_agent.models import RestoreContext


class ChatStoreRestoreTests(unittest.TestCase):
    def restore_context(self) -> RestoreContext:
        return RestoreContext.model_validate(
            {
                "schema_version": 1,
                "conversation_id": str(uuid4()),
                "revision": 7,
                "summary": "Earlier factual summary.",
                "messages": [
                    {"role": "user", "content": "Show revenue"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "execute_sql",
                                    "arguments": '{"sql":"select 1"}',
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call-1",
                        "name": "execute_sql",
                        "content": '{"ok":true,"rows_preview":[{"value":1}]}',
                    },
                    {"role": "assistant", "content": "Revenue is 1."},
                ],
            }
        )

    def test_restore_and_existing_does_not_duplicate(self) -> None:
        store = ChatStore()
        context = self.restore_context()
        chat_id, session, disposition = store.get_or_restore("chat-1", context)
        self.assertEqual(disposition, SessionDisposition.RESTORED)
        self.assertEqual(session.context_revision, 7)
        before = list(session.messages)
        same_id, same_session, disposition = store.get_or_restore("chat-1", context)
        self.assertEqual((same_id, disposition), (chat_id, SessionDisposition.EXISTING))
        self.assertIs(same_session, session)
        self.assertEqual(same_session.messages, before)

    def test_unknown_chat_requires_context(self) -> None:
        with self.assertRaises(ChatContextMissingError):
            ChatStore().get_or_restore("unknown", None)

    def test_invalid_tool_sequence_is_rejected(self) -> None:
        payload = self.restore_context().model_dump(mode="json")
        payload["messages"][2]["tool_call_id"] = "wrong"
        with self.assertRaises(ValidationError):
            RestoreContext.model_validate(payload)


class CheckpointTests(unittest.TestCase):
    def test_reasoning_is_removed_and_sql_rows_are_bounded(self) -> None:
        messages = [
            {"role": "user", "content": "query"},
            {
                "role": "assistant",
                "content": None,
                "reasoning_content": "secret reasoning",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "execute_sql", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": json.dumps(
                    {
                        "ok": True,
                        "columns": ["value"],
                        "rows": [{"value": n} for n in range(1000)],
                        "row_count": 1000,
                        "total_row_count": 1000,
                        "truncated": False,
                    }
                ),
            },
            {"role": "assistant", "content": "done", "reasoning_content": "hidden"},
        ]
        canonical = canonicalize_turn_messages(messages)
        encoded = json.dumps(canonical)
        self.assertNotIn("reasoning", encoded)
        result = json.loads(canonical[2]["content"])
        self.assertEqual(len(result["rows_preview"]), 10)
        self.assertNotIn("rows", result)

    def test_arbitrary_tool_result_is_bounded(self) -> None:
        compact = compact_tool_result("run_python", json.dumps({"stdout": "x" * 100000}))
        self.assertLessEqual(len(compact.encode()), 16384)

    def test_high_water_context_is_summarized_without_current_prompt(self) -> None:
        messages = [
            {"role": "user", "content": "old " + "x" * 100},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "current"},
        ]
        completion = iter(
            [{"type": "llm_complete", "message": {"role": "assistant", "content": "factual summary"}}]
        )
        with (
            patch("services.main_agent.context.CONTEXT_COMPACTION_HIGH_WATER_BYTES", 10),
            patch("services.main_agent.context.stream_chat_completion", return_value=completion),
        ):
            summary, update = compact_conversation_if_needed(
                messages, "", str(uuid4())
            )
        self.assertEqual(summary, "factual summary")
        self.assertEqual(messages, [{"role": "user", "content": "current"}])
        self.assertEqual(update["summary"], "factual summary")


if __name__ == "__main__":
    unittest.main()
