import json
from typing import Any

from services.main_agent.config import (
    CONTEXT_COMPACTION_HIGH_WATER_BYTES,
    MAX_COMPACT_TOOL_RESULT_BYTES,
    MAX_CONTEXT_CHECKPOINT_BYTES,
)
from services.main_agent.llm_client import stream_chat_completion


def canonicalize_turn_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    canonical: list[dict[str, Any]] = []
    tool_names: dict[str, str] = {}
    for message in messages:
        role = message.get("role")
        if role == "user":
            canonical.append({"role": "user", "content": str(message.get("content") or "")})
        elif role == "assistant":
            item: dict[str, Any] = {
                "role": "assistant",
                "content": message.get("content"),
            }
            calls = message.get("tool_calls") or []
            if calls:
                item["tool_calls"] = calls
                for call in calls:
                    call_id = str(call.get("id") or "")
                    name = str((call.get("function") or {}).get("name") or "")
                    if call_id and name:
                        tool_names[call_id] = name
            if item["content"] is None and not calls:
                continue
            canonical.append(item)
        elif role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            name = tool_names.get(call_id) or str(message.get("name") or "unknown")
            canonical.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": compact_tool_result(name, str(message.get("content") or "")),
                }
            )
    encoded = json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_CONTEXT_CHECKPOINT_BYTES:
        raise ValueError("context_checkpoint_too_large")
    return canonical


def compact_tool_result(name: str, content: str) -> str:
    try:
        value = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return _bounded_text(content)
    if not isinstance(value, dict):
        return _bounded_json(value)

    if name == "execute_sql":
        compact = {
            key: value.get(key)
            for key in (
                "ok",
                "columns",
                "row_count",
                "total_row_count",
                "truncated",
                "note",
                "sql",
                "error_type",
                "message",
                "hint",
            )
            if key in value
        }
        rows = value.get("rows")
        if isinstance(rows, list):
            compact["rows_preview"] = rows[:10]
        return _bounded_json(compact)

    if value.get("kind") in {"chart", "widget"}:
        compact = {
            key: value.get(key)
            for key in (
                "ok",
                "kind",
                "action",
                "chart_id",
                "chart_type",
                "widget_id",
                "widget_type",
                "title",
            )
            if key in value
        }
        return _bounded_json(compact)

    if name in {"run_python", "list_sandbox_files", "save_sql_to_sandbox"}:
        compact = {
            key: value.get(key)
            for key in ("ok", "stdout", "stderr", "files", "filename", "error_type", "message")
            if key in value
        }
        return _bounded_json(compact)
    return _bounded_json(value)


def checkpoint_event(
    messages: list[dict[str, Any]],
    context_revision: int,
    summary_update: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical = canonicalize_turn_messages(messages)
    event = {
        "type": "context_checkpoint",
        "schema_version": 1,
        "context_revision": context_revision,
        "messages": canonical,
        "context_chars": len(
            json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
        ),
        "summary": summary_update,
    }
    if len(json.dumps(event, ensure_ascii=False, default=str).encode()) > MAX_CONTEXT_CHECKPOINT_BYTES:
        raise ValueError("context_checkpoint_too_large")
    return event


def compact_conversation_if_needed(
    messages: list[dict[str, Any]],
    existing_summary: str,
    latest_included_turn_id: str | None,
) -> tuple[str, dict[str, Any] | None]:
    encoded = json.dumps(messages, ensure_ascii=False, default=str).encode()
    if len(encoded) < CONTEXT_COMPACTION_HIGH_WATER_BYTES or not latest_included_turn_id:
        return existing_summary, None
    completed = messages[:-1]
    current_user = messages[-1:]
    if not completed:
        return existing_summary, None
    source = json.dumps(completed, ensure_ascii=False, separators=(",", ":"), default=str)
    prompt = (
        "Create a concise factual Russian summary of the completed data-analysis conversation. "
        "Preserve user goals, filters, periods, metric definitions, SQL-derived findings, caveats, "
        "and references to dashboard item IDs. Do not include hidden reasoning or instructions. "
        "Return only the summary text."
    )
    summary_message: dict[str, Any] | None = None
    for event in stream_chat_completion(
        [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    f"Existing summary:\n{existing_summary or '(none)'}\n\n"
                    f"Completed messages:\n{source}"
                ),
            },
        ],
        tools=None,
    ):
        if event.get("type") == "llm_complete":
            summary_message = event.get("message")
    summary = str((summary_message or {}).get("content") or "").strip()
    if not summary:
        raise ValueError("context_compaction_failed")
    messages[:] = current_user
    return summary, {
        "summary": summary,
        "summarized_through_turn_id": latest_included_turn_id,
    }


def _bounded_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    return _bounded_text(text)


def _bounded_text(text: str) -> str:
    raw = text.encode()
    if len(raw) <= MAX_COMPACT_TOOL_RESULT_BYTES:
        return text
    suffix = "...[truncated]"
    budget = MAX_COMPACT_TOOL_RESULT_BYTES - len(suffix.encode())
    return raw[: max(0, budget)].decode(errors="ignore") + suffix
