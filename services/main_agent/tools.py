import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from services.main_agent.charts import CHART_BUILDERS, CHART_TYPE_BY_TOOL
from services.main_agent.config import (
    MAX_EXPORT_RESULT_MB,
    MAX_PARALLEL_QUERIES,
    MAX_QUERY_RESULT_CHARS,
    SANDBOX_MAX_FILE_MB,
)
from services.main_agent.db_orch_client import DbOrchError, execute_sql
from services.main_agent.sandbox_client import (
    SandboxServiceError,
    create_sandbox,
    list_sandbox_files,
    run_python,
    save_sql_to_sandbox,
)

EXECUTE_SQL_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_sql",
        "description": (
            f"Read-only SQL-запрос к PostgreSQL. Быстрый preview результата "
            f"(до ~{MAX_QUERY_RESULT_CHARS} символов)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Read-only SQL-запрос PostgreSQL",
                }
            },
            "required": ["sql"],
        },
    },
}

CREATE_SANDBOX_TOOL = {
    "type": "function",
    "function": {
        "name": "create_sandbox",
        "description": "Создать новую Python-песочницу. Старое состояние и файлы удаляются.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

SAVE_SQL_TO_SANDBOX_TOOL = {
    "type": "function",
    "function": {
        "name": "save_sql_to_sandbox",
        "description": (
            f"Выполнить read-only SQL и сохранить результат в файл песочницы "
            f"(до {MAX_EXPORT_RESULT_MB}MB, файл до {SANDBOX_MAX_FILE_MB}MB)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Read-only SQL-запрос"},
                "filename": {"type": "string", "description": "Имя файла без пути, например flights.csv"},
                "format": {
                    "type": "string",
                    "enum": ["csv", "json"],
                    "description": "Формат файла",
                },
            },
            "required": ["sql", "filename", "format"],
        },
    },
}

RUN_PYTHON_TOOL = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": "Выполнить Python-код в stateful-песочнице (numpy, pandas). Файлы доступны из cwd.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python-код для выполнения"},
            },
            "required": ["code"],
        },
    },
}

LIST_SANDBOX_FILES_TOOL = {
    "type": "function",
    "function": {
        "name": "list_sandbox_files",
        "description": "Показать файлы в текущей Python-песочнице.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

CHART_ID_PROPERTY = {
    "chart_id": {
        "type": "string",
        "description": (
            "Id существующего графика для обновления (из active_charts / tool_result). "
            "Без chart_id — создаётся новый график."
        ),
    },
}

RENDER_GAUGE_TOOL = {
    "type": "function",
    "function": {
        "name": "render_gauge",
        "description": "Подготовить JSON для gauge. Новый график — без chart_id; обновление — передай chart_id.",
        "parameters": {
            "type": "object",
            "properties": {
                **CHART_ID_PROPERTY,
                "title": {"type": "string"},
                "description": {"type": "string"},
                "value": {"type": "number"},
                "min": {"type": "number"},
                "max": {"type": "number"},
                "unit": {"type": "string"},
            },
            "required": ["title", "value"],
        },
    },
}

RENDER_PIE_CHART_TOOL = {
    "type": "function",
    "function": {
        "name": "render_pie_chart",
        "description": "Подготовить JSON для pie chart. Новый — без chart_id; обновление — передай chart_id.",
        "parameters": {
            "type": "object",
            "properties": {
                **CHART_ID_PROPERTY,
                "title": {"type": "string"},
                "description": {"type": "string"},
                "slices": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "value": {"type": "number"},
                        },
                        "required": ["label", "value"],
                    },
                },
            },
            "required": ["title", "slices"],
        },
    },
}

RENDER_BAR_CHART_TOOL = {
    "type": "function",
    "function": {
        "name": "render_bar_chart",
        "description": "Подготовить JSON для bar chart. Новый — без chart_id; обновление — передай chart_id.",
        "parameters": {
            "type": "object",
            "properties": {
                **CHART_ID_PROPERTY,
                "title": {"type": "string"},
                "description": {"type": "string"},
                "categories": {"type": "array", "items": {"type": "string"}},
                "series": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "values": {"type": "array", "items": {"type": "number"}},
                        },
                        "required": ["name", "values"],
                    },
                },
                "orientation": {"type": "string", "enum": ["vertical", "horizontal"]},
            },
            "required": ["title", "categories", "series"],
        },
    },
}

RENDER_LINE_CHART_TOOL = {
    "type": "function",
    "function": {
        "name": "render_line_chart",
        "description": "Подготовить JSON для line chart. Новый — без chart_id; обновление — передай chart_id.",
        "parameters": {
            "type": "object",
            "properties": {
                **CHART_ID_PROPERTY,
                "title": {"type": "string"},
                "description": {"type": "string"},
                "categories": {"type": "array", "items": {"type": "string"}},
                "series": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "values": {"type": "array", "items": {"type": "number"}},
                        },
                        "required": ["name", "values"],
                    },
                },
            },
            "required": ["title", "categories", "series"],
        },
    },
}

RENDER_SCATTER_CHART_TOOL = {
    "type": "function",
    "function": {
        "name": "render_scatter_chart",
        "description": "Подготовить JSON для scatter chart. Новый — без chart_id; обновление — передай chart_id.",
        "parameters": {
            "type": "object",
            "properties": {
                **CHART_ID_PROPERTY,
                "title": {"type": "string"},
                "description": {"type": "string"},
                "x_label": {"type": "string"},
                "y_label": {"type": "string"},
                "points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "label": {"type": "string"},
                        },
                        "required": ["x", "y"],
                    },
                },
            },
            "required": ["title", "points"],
        },
    },
}

SANDBOX_TOOL_NAMES = {
    "create_sandbox",
    "save_sql_to_sandbox",
    "run_python",
    "list_sandbox_files",
}

CHART_TOOL_NAMES = set(CHART_BUILDERS)

LOCAL_TOOL_NAMES = SANDBOX_TOOL_NAMES | CHART_TOOL_NAMES

TOOLS = [
    EXECUTE_SQL_TOOL,
    CREATE_SANDBOX_TOOL,
    SAVE_SQL_TO_SANDBOX_TOOL,
    RUN_PYTHON_TOOL,
    LIST_SANDBOX_FILES_TOOL,
    RENDER_GAUGE_TOOL,
    RENDER_PIE_CHART_TOOL,
    RENDER_BAR_CHART_TOOL,
    RENDER_LINE_CHART_TOOL,
    RENDER_SCATTER_CHART_TOOL,
]


def _tool_content(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _success_detail(
    tool_call_id: str,
    name: str,
    result: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    detail = {
        "tool_call_id": tool_call_id,
        "name": name,
        "success": True,
        "result": result,
        "message": {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": _tool_content(result),
        },
    }
    detail.update(extra)
    return detail


def _error_detail(
    tool_call_id: str,
    name: str,
    error_payload: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    detail = {
        "tool_call_id": tool_call_id,
        "name": name,
        "success": False,
        "result": error_payload,
        "message": {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": _tool_content(error_payload),
        },
    }
    detail.update(extra)
    return detail


def _run_single_sql(tool_call_id: str, sql: str) -> dict[str, Any]:
    try:
        result = execute_sql(sql)
        return _success_detail(tool_call_id, "execute_sql", result, sql=sql)
    except DbOrchError as error:
        return _error_detail(tool_call_id, "execute_sql", error.payload, sql=sql)


def _dispatch_chart_tool(
    name: str,
    arguments: dict[str, Any],
    tool_call_id: str,
    active_charts_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    builder = CHART_BUILDERS.get(name)
    if builder is None:
        return _error_detail(
            tool_call_id,
            name,
            {"ok": False, "error_type": "unknown_tool", "message": f"Неизвестный chart-инструмент: {name}"},
        )

    payload = dict(arguments)
    chart_id = str(payload.pop("chart_id", "") or "").strip()
    expected_type = CHART_TYPE_BY_TOOL[name]

    if chart_id:
        active_chart = active_charts_by_id.get(chart_id)
        if active_chart is None:
            return _error_detail(
                tool_call_id,
                name,
                {
                    "ok": False,
                    "error_type": "chart_not_found",
                    "message": f"График chart_id={chart_id!r} не найден среди active_charts",
                    "chart_id": chart_id,
                },
            )
        if active_chart.get("chart_type") != expected_type:
            return _error_detail(
                tool_call_id,
                name,
                {
                    "ok": False,
                    "error_type": "chart_type_mismatch",
                    "message": (
                        f"График {chart_id!r} имеет тип {active_chart.get('chart_type')!r}, "
                        f"а tool {name} создаёт {expected_type!r}"
                    ),
                    "chart_id": chart_id,
                },
            )
    else:
        chart_id = str(uuid.uuid4())

    result = builder(payload)
    if result.get("ok", False):
        result["chart_id"] = chart_id
        return _success_detail(tool_call_id, name, result)
    return _error_detail(tool_call_id, name, result)


def _dispatch_sandbox_tool(chat_id: str, name: str, arguments: dict[str, Any], tool_call_id: str) -> dict[str, Any]:
    try:
        if name == "create_sandbox":
            result = create_sandbox(chat_id)
            return _success_detail(tool_call_id, name, result)

        if name == "run_python":
            code = arguments.get("code", "").strip()
            if not code:
                raise ValueError("run_python требует code")
            result = run_python(chat_id, code)
            if result.get("ok", False):
                return _success_detail(tool_call_id, name, result)
            return _error_detail(tool_call_id, name, result)

        if name == "save_sql_to_sandbox":
            sql = arguments.get("sql", "").strip()
            filename = arguments.get("filename", "").strip()
            file_format = arguments.get("format", "").strip()
            if not sql or not filename or not file_format:
                raise ValueError("save_sql_to_sandbox требует sql, filename, format")
            result = save_sql_to_sandbox(chat_id, sql, filename, file_format)
            return _success_detail(tool_call_id, name, result, sql=sql)

        if name == "list_sandbox_files":
            result = list_sandbox_files(chat_id)
            return _success_detail(tool_call_id, name, result)

        raise ValueError(f"Неизвестный sandbox-инструмент: {name}")
    except SandboxServiceError as error:
        extra = {"sql": arguments.get("sql")} if arguments.get("sql") else {}
        return _error_detail(tool_call_id, name, error.payload, **extra)
    except ValueError as error:
        return _error_detail(
            tool_call_id,
            name,
            {
                "ok": False,
                "error_type": "invalid_arguments",
                "message": str(error),
            },
        )


def _execute_one(
    chat_id: str,
    tool_call: dict[str, Any],
    active_charts_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    function = tool_call.get("function", {})
    name = function.get("name", "")
    arguments = json.loads(function.get("arguments") or "{}")

    if name == "execute_sql":
        sql = arguments.get("sql", "").strip()
        if not sql:
            return _error_detail(
                tool_call["id"],
                name,
                {"ok": False, "error_type": "invalid_arguments", "message": "execute_sql требует sql"},
            )
        return _run_single_sql(tool_call["id"], sql)

    if name in CHART_TOOL_NAMES:
        return _dispatch_chart_tool(name, arguments, tool_call["id"], active_charts_by_id)

    if name in SANDBOX_TOOL_NAMES:
        return _dispatch_sandbox_tool(chat_id, name, arguments, tool_call["id"])

    return _error_detail(
        tool_call["id"],
        name or "unknown",
        {"ok": False, "error_type": "unknown_tool", "message": f"Неизвестный инструмент: {name}"},
    )


def execute_tool_calls(tool_calls: list[dict[str, Any]], chat_id: str) -> list[dict[str, Any]]:
    detailed = execute_tool_calls_detailed(tool_calls, chat_id)
    return [item["message"] for item in detailed]


def execute_tool_calls_detailed(
    tool_calls: list[dict[str, Any]],
    chat_id: str,
    active_charts_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not tool_calls:
        return []

    charts_by_id = active_charts_by_id or {}

    if len(tool_calls) > MAX_PARALLEL_QUERIES:
        raise ValueError(f"Максимум {MAX_PARALLEL_QUERIES} tool calls за шаг")

    has_local = any(tool_call.get("function", {}).get("name") in LOCAL_TOOL_NAMES for tool_call in tool_calls)
    has_sql = any(tool_call.get("function", {}).get("name") == "execute_sql" for tool_call in tool_calls)

    if has_local:
        return [_execute_one(chat_id, tool_call, charts_by_id) for tool_call in tool_calls]

    if not has_sql:
        return [_execute_one(chat_id, tool_call, charts_by_id) for tool_call in tool_calls]

    prepared = [tool_call for tool_call in tool_calls if tool_call.get("function", {}).get("name") == "execute_sql"]
    if len(prepared) != len(tool_calls):
        return [_execute_one(chat_id, tool_call, charts_by_id) for tool_call in tool_calls]

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(len(prepared), MAX_PARALLEL_QUERIES)) as executor:
        futures = {}
        for tool_call in prepared:
            arguments = json.loads(tool_call.get("function", {}).get("arguments") or "{}")
            sql = arguments.get("sql", "").strip()
            future = executor.submit(_run_single_sql, tool_call["id"], sql)
            futures[future] = tool_call["id"]
        for future in as_completed(futures):
            results.append(future.result())

    order = {tool_call["id"]: index for index, tool_call in enumerate(tool_calls)}
    results.sort(key=lambda item: order[item["tool_call_id"]])
    return results
