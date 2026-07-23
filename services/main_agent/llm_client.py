import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterator

import httpx

from services.main_agent.config import (
    LLM_LOG_PATH,
    LLM_TIMEOUT_SEC,
    LOG_LLM_CALLS,
    MODEL_API_KEY,
    MODEL_NAME,
    MODEL_URL,
)

logger = logging.getLogger(__name__)


def _chat_completions_url() -> str:
    base = MODEL_URL.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def log_llm_call(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    response: dict[str, Any],
    error: str | None = None,
) -> None:
    if not LOG_LLM_CALLS:
        return
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": MODEL_NAME,
        "request": {
            "messages": messages,
            "tools": tools,
        },
        "response": response,
        "error": error,
    }

    LLM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LLM_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    logger.info("LLM call logged to %s", LLM_LOG_PATH)


class StreamedAssistantMessage:
    def __init__(self) -> None:
        self.reasoning_content = ""
        self.content = ""
        self.tool_calls: dict[int, dict[str, Any]] = {}

    def apply_delta(self, delta: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        reasoning_delta = delta.get("reasoning_content")
        if reasoning_delta:
            self.reasoning_content += reasoning_delta
            events.append({"type": "reasoning_delta", "content": reasoning_delta})

        content_delta = delta.get("content")
        if content_delta:
            self.content += content_delta
            events.append({"type": "content_delta", "content": content_delta})

        for tool_call_delta in delta.get("tool_calls") or []:
            index = tool_call_delta["index"]
            if index not in self.tool_calls:
                self.tool_calls[index] = {
                    "id": tool_call_delta.get("id", ""),
                    "type": tool_call_delta.get("type", "function"),
                    "function": {"name": "", "arguments": ""},
                }

            current = self.tool_calls[index]
            if tool_call_delta.get("id"):
                current["id"] = tool_call_delta["id"]

            function_delta = tool_call_delta.get("function") or {}
            if function_delta.get("name"):
                current["function"]["name"] += function_delta["name"]
            if function_delta.get("arguments"):
                current["function"]["arguments"] += function_delta["arguments"]

        return events

    def to_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": self.content or None,
        }
        if self.reasoning_content:
            message["reasoning_content"] = self.reasoning_content

        if self.tool_calls:
            message["tool_calls"] = [
                self.tool_calls[index] for index in sorted(self.tool_calls)
            ]

        return message


def stream_chat_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> Iterator[dict[str, Any]]:
    if not MODEL_API_KEY:
        raise RuntimeError("MODEL_API_KEY не задан")

    payload: dict[str, Any] = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {
        "Authorization": f"Bearer {MODEL_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    accumulator = StreamedAssistantMessage()
    raw_chunks: list[str] = []

    try:
        with httpx.Client(timeout=LLM_TIMEOUT_SEC) as client:
            with client.stream(
                "POST",
                _chat_completions_url(),
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue

                    payload_line = line.removeprefix("data:").strip()
                    if payload_line == "[DONE]":
                        break

                    raw_chunks.append(payload_line)
                    chunk = json.loads(payload_line)
                    choice = chunk.get("choices", [{}])[0]
                    delta = choice.get("delta") or {}
                    for event in accumulator.apply_delta(delta):
                        yield event
    except Exception as error:
        log_llm_call(messages=messages, tools=tools, response={}, error=str(error))
        raise

    message = accumulator.to_message()
    log_llm_call(
        messages=messages,
        tools=tools,
        response={
            "stream": True,
            "raw_chunks_count": len(raw_chunks),
            "message": message,
        },
    )
    yield {"type": "llm_complete", "message": message}
