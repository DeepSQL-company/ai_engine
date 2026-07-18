from typing import Any, Iterator

from services.main_agent.config import (
    MAX_AGENT_ITERATIONS,
    MAX_EXPORT_RESULT_MB,
    MAX_PARALLEL_QUERIES,
    MAX_QUERY_RESULT_CHARS,
    SANDBOX_EXEC_TIMEOUT_SEC,
    SANDBOX_MAX_FILES,
    SYSTEM_PROMPT_TEMPLATE,
)
from services.main_agent.db_orch_client import DbOrchError, fetch_metadata_text
from services.main_agent.llm_client import stream_chat_completion
from services.main_agent.tools import TOOLS, execute_tool_calls_detailed


class AgentError(Exception):
    pass


def stream_agent(conversation: list[dict[str, Any]], chat_id: str) -> Iterator[dict[str, Any]]:
    if not conversation or conversation[-1].get("role") != "user":
        raise AgentError("conversation должна заканчиваться user-сообщением")

    yield {"type": "status", "stage": "metadata", "message": "Загрузка метаданных БД"}

    try:
        metadata = fetch_metadata_text()
    except DbOrchError as error:
        raise AgentError(f"Не удалось получить метаданные из db_orch: {error}") from error

    yield {
        "type": "metadata",
        "content": metadata,
        "length": len(metadata),
    }

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        db_metadata=metadata,
        max_query_result_chars=MAX_QUERY_RESULT_CHARS,
        max_export_result_mb=MAX_EXPORT_RESULT_MB,
        sandbox_max_files=SANDBOX_MAX_FILES,
        sandbox_exec_timeout_sec=SANDBOX_EXEC_TIMEOUT_SEC,
        max_parallel_queries=MAX_PARALLEL_QUERIES,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *conversation,
    ]

    sql_calls_count = 0
    tool_calls_count = 0
    turn_start_index = len(conversation)

    for iteration in range(1, MAX_AGENT_ITERATIONS + 1):
        yield {
            "type": "iteration_start",
            "iteration": iteration,
        }

        assistant_message: dict[str, Any] | None = None

        for llm_event in stream_chat_completion(messages, tools=TOOLS):
            if llm_event["type"] in {"reasoning_delta", "content_delta"}:
                yield {
                    **llm_event,
                    "iteration": iteration,
                }
                continue

            if llm_event["type"] == "llm_complete":
                assistant_message = llm_event["message"]

        if assistant_message is None:
            raise AgentError("LLM не вернул ответ")

        reasoning = assistant_message.get("reasoning_content") or ""
        content = assistant_message.get("content") or ""
        tool_calls = assistant_message.get("tool_calls") or []

        if reasoning:
            yield {
                "type": "reasoning",
                "iteration": iteration,
                "content": reasoning,
            }

        if content:
            yield {
                "type": "assistant_message",
                "iteration": iteration,
                "content": content,
            }

        messages.append(assistant_message)
        conversation.append(assistant_message)

        if not tool_calls:
            answer = content.strip()
            if not answer and reasoning.strip():
                answer = reasoning.strip()
            if not answer:
                raise AgentError("LLM вернул пустой ответ")

            yield {
                "type": "answer",
                "content": answer,
            }
            yield {
                "type": "done",
                "sql_calls_count": sql_calls_count,
                "tool_calls_count": tool_calls_count,
                "iterations": iteration,
                "turn_messages_count": len(conversation) - turn_start_index,
                "history_messages_count": len(conversation),
            }
            return

        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            yield {
                "type": "tool_start",
                "iteration": iteration,
                "tool_call_id": tool_call.get("id"),
                "name": function.get("name"),
                "input": function.get("arguments"),
            }

        tool_details = execute_tool_calls_detailed(tool_calls, chat_id)
        tool_calls_count += len(tool_details)
        sql_calls_count += sum(1 for item in tool_details if item["name"] == "execute_sql")

        for detail in tool_details:
            event: dict[str, Any] = {
                "type": "tool_result",
                "iteration": iteration,
                "tool_call_id": detail["tool_call_id"],
                "name": detail["name"],
                "success": detail["success"],
                "result": detail["result"],
            }
            if detail.get("sql"):
                event["sql"] = detail["sql"]
            if detail.get("success") and detail["result"].get("kind") == "chart":
                event["chart_type"] = detail["result"].get("chart_type")
            yield event
            messages.append(detail["message"])
            conversation.append(detail["message"])

    raise AgentError(f"Превышен лимит итераций агента ({MAX_AGENT_ITERATIONS})")
