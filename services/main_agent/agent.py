from typing import Any, Iterator

from services.main_agent.charts import format_active_charts_for_prompt
from services.main_agent.config import (
    MAX_AGENT_ITERATIONS,
    MAX_EXPORT_RESULT_MB,
    MAX_PARALLEL_QUERIES,
    MAX_QUERY_RESULT_CHARS,
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
    SANDBOX_EXEC_TIMEOUT_SEC,
    SANDBOX_MAX_FILES,
    SYSTEM_PROMPT_TEMPLATE,
)
from services.main_agent.db_orch_client import DbOrchError, fetch_metadata_text
from services.main_agent.llm_client import stream_chat_completion
from services.main_agent.tools import TOOLS, execute_tool_calls_detailed
from services.main_agent.widgets import format_active_widgets_for_prompt


class AgentError(Exception):
    pass


def stream_agent(
    conversation: list[dict[str, Any]],
    chat_id: str,
    active_charts: list[dict[str, Any]] | None = None,
    active_widgets: list[dict[str, Any]] | None = None,
) -> Iterator[dict[str, Any]]:
    if not conversation or conversation[-1].get("role") != "user":
        raise AgentError("conversation должна заканчиваться user-сообщением")

    active_charts = active_charts or []
    active_widgets = active_widgets or []
    charts_by_id = {chart["chart_id"]: chart for chart in active_charts}
    widgets_by_id = {widget["widget_id"]: widget for widget in active_widgets}

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
        active_charts=format_active_charts_for_prompt(active_charts),
        active_widgets=format_active_widgets_for_prompt(active_widgets),
        max_query_result_chars=MAX_QUERY_RESULT_CHARS,
        max_export_result_mb=MAX_EXPORT_RESULT_MB,
        sandbox_max_files=SANDBOX_MAX_FILES,
        sandbox_exec_timeout_sec=SANDBOX_EXEC_TIMEOUT_SEC,
        max_parallel_queries=MAX_PARALLEL_QUERIES,
        max_table_rows=MAX_TABLE_ROWS,
        max_table_columns=MAX_TABLE_COLUMNS,
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

        tool_details = execute_tool_calls_detailed(
            tool_calls,
            chat_id,
            charts_by_id,
            widgets_by_id,
            iterations_exhausted=iteration >= MAX_AGENT_ITERATIONS,
        )
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
                event["chart_id"] = detail["result"].get("chart_id")
                if detail["result"].get("action"):
                    event["action"] = detail["result"]["action"]
            if detail.get("success") and detail["result"].get("kind") == "widget":
                event["widget_type"] = detail["result"].get("widget_type")
                event["widget_id"] = detail["result"].get("widget_id")
            yield event
            messages.append(detail["message"])
            conversation.append(detail["message"])

    raise AgentError(f"Превышен лимит итераций агента ({MAX_AGENT_ITERATIONS})")
