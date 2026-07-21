import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from services.main_agent.charts import CHART_BUILDERS, CHART_TYPE_BY_TOOL, build_remove_chart
from services.main_agent.config import (
    ITERATIONS_EXHAUSTED_TOOL_MESSAGE,
    MAX_DATA_QUALITY_CHECKS,
    MAX_EXPORT_RESULT_MB,
    MAX_INSIGHT_POINTS,
    MAX_PARALLEL_QUERIES,
    MAX_QUERY_RESULT_CHARS,
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
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
from services.main_agent.widgets import WIDGET_BUILDERS, WIDGET_TYPE_BY_TOOL

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

REMOVE_CHART_TOOL = {
    "type": "function",
    "function": {
        "name": "remove_chart",
        "description": (
            "Удалить график с дашборда клиента. "
            "Передай chart_id из active_charts или из предыдущего tool_result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chart_id": {
                    "type": "string",
                    "description": "Id графика, который нужно удалить с экрана клиента.",
                },
            },
            "required": ["chart_id"],
        },
    },
}

WIDGET_ID_PROPERTY = {
    "widget_id": {
        "type": "string",
        "description": (
            "Id существующего виджета для обновления (из active_widgets / tool_result). "
            "Без widget_id — создаётся новый виджет."
        ),
    },
}

RENDER_KPI_TOOL = {
    "type": "function",
    "function": {
        "name": "render_kpi",
        "description": "Подготовить JSON для KPI-карточки. Новый — без widget_id; обновление — передай widget_id.",
        "parameters": {
            "type": "object",
            "properties": {
                **WIDGET_ID_PROPERTY,
                "title": {"type": "string"},
                "description": {"type": "string"},
                "label": {"type": "string", "description": "Подпись к метрике, например «Выручка»"},
                "value": {"type": "number"},
                "unit": {"type": "string"},
                "period": {"type": "string"},
                "status": {"type": "string", "enum": ["good", "warning", "critical", "neutral", "info"]},
                "change": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number"},
                        "direction": {"type": "string", "enum": ["up", "down", "flat"]},
                        "unit": {"type": "string", "description": "percent или абсолютная единица"},
                        "label": {"type": "string"},
                    },
                    "required": ["value"],
                },
            },
            "required": ["title", "value"],
        },
    },
}

RENDER_INSIGHT_TOOL = {
    "type": "function",
    "function": {
        "name": "render_insight",
        "description": "Подготовить JSON для insight-карточки. Новый — без widget_id; обновление — передай widget_id.",
        "parameters": {
            "type": "object",
            "properties": {
                **WIDGET_ID_PROPERTY,
                "title": {"type": "string"},
                "description": {"type": "string"},
                "summary": {"type": "string", "description": "Главный вывод в 1-2 предложениях"},
                "period": {"type": "string"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "evidence": {"type": "string"},
                        },
                        "required": ["text"],
                    },
                    "description": f"Ключевые тезисы, до {MAX_INSIGHT_POINTS} пунктов",
                },
            },
            "required": ["title", "summary", "points"],
        },
    },
}

RENDER_DATA_QUALITY_TOOL = {
    "type": "function",
    "function": {
        "name": "render_data_quality",
        "description": "Подготовить JSON для data quality виджета. Новый — без widget_id; обновление — передай widget_id.",
        "parameters": {
            "type": "object",
            "properties": {
                **WIDGET_ID_PROPERTY,
                "title": {"type": "string"},
                "description": {"type": "string"},
                "status": {"type": "string", "enum": ["good", "warning", "critical", "neutral", "info"]},
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "label": {"type": "string"},
                            "status": {"type": "string", "enum": ["good", "warning", "critical", "neutral", "info"]},
                            "value": {"type": "string"},
                            "detail": {"type": "string"},
                        },
                        "required": ["name", "label", "status"],
                    },
                    "description": f"Проверки качества данных, до {MAX_DATA_QUALITY_CHECKS} штук",
                },
                "freshness": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "value": {"type": "string"},
                        "status": {"type": "string", "enum": ["good", "warning", "critical", "neutral", "info"]},
                    },
                    "required": ["label", "value"],
                },
            },
            "required": ["title", "status", "checks"],
        },
    },
}

RENDER_TABLE_TOOL = {
    "type": "function",
    "function": {
        "name": "render_table",
        "description": "Подготовить JSON для таблицы. Новый — без widget_id; обновление — передай widget_id.",
        "parameters": {
            "type": "object",
            "properties": {
                **WIDGET_ID_PROPERTY,
                "title": {"type": "string"},
                "description": {"type": "string"},
                "columns": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "label": {"type": "string"},
                            "format": {
                                "type": "string",
                                "enum": ["text", "number", "currency", "percent", "date", "datetime"],
                            },
                        },
                        "required": ["key", "label"],
                    },
                    "description": f"До {MAX_TABLE_COLUMNS} колонок",
                },
                "rows": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": f"До {MAX_TABLE_ROWS} строк; ключи должны совпадать с columns.key",
                },
                "sort": {
                    "type": "object",
                    "properties": {
                        "column": {"type": "string"},
                        "direction": {"type": "string", "enum": ["asc", "desc"]},
                    },
                    "required": ["column"],
                },
            },
            "required": ["title", "columns", "rows"],
        },
    },
}

SANDBOX_TOOL_NAMES = {
    "create_sandbox",
    "save_sql_to_sandbox",
    "run_python",
    "list_sandbox_files",
}

CHART_TOOL_NAMES = set(CHART_BUILDERS) | {"remove_chart"}
CHART_RENDER_TOOL_NAMES = set(CHART_BUILDERS)
WIDGET_TOOL_NAMES = set(WIDGET_BUILDERS)

LOCAL_TOOL_NAMES = SANDBOX_TOOL_NAMES | CHART_TOOL_NAMES | WIDGET_TOOL_NAMES

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
    REMOVE_CHART_TOOL,
    RENDER_KPI_TOOL,
    RENDER_INSIGHT_TOOL,
    RENDER_DATA_QUALITY_TOOL,
    RENDER_TABLE_TOOL,
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


def _tool_name(tool_call: dict[str, Any]) -> str:
    return (tool_call.get("function") or {}).get("name") or "unknown"


def _tool_batch_error(
    tool_calls: list[dict[str, Any]],
    error_type: str,
    message: str,
) -> list[dict[str, Any]]:
    return [
        _error_detail(
            tool_call.get("id") or f"unknown-{index}",
            _tool_name(tool_call),
            {
                "ok": False,
                "error_type": error_type,
                "message": message,
            },
        )
        for index, tool_call in enumerate(tool_calls)
    ]


def _parse_tool_arguments(tool_call: dict[str, Any]) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    name = _tool_name(tool_call)
    raw_arguments = (tool_call.get("function") or {}).get("arguments") or "{}"
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as error:
        return name, None, {
            "ok": False,
            "error_type": "invalid_tool_arguments",
            "message": f"Tool arguments are not valid JSON: {error}",
        }
    if not isinstance(arguments, dict):
        return name, None, {
            "ok": False,
            "error_type": "invalid_tool_arguments",
            "message": "Tool arguments must be a JSON object.",
        }
    return name, arguments, None


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


def _dispatch_remove_chart(
    arguments: dict[str, Any],
    tool_call_id: str,
    active_charts_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    chart_id = str(arguments.get("chart_id", "") or "").strip()
    if not chart_id:
        return _error_detail(
            tool_call_id,
            "remove_chart",
            {
                "ok": False,
                "error_type": "chart_validation_error",
                "message": "remove_chart требует chart_id",
            },
        )

    active_chart = active_charts_by_id.get(chart_id)
    if active_chart is None:
        return _error_detail(
            tool_call_id,
            "remove_chart",
            {
                "ok": False,
                "error_type": "chart_not_found",
                "message": f"График chart_id={chart_id!r} не найден среди active_charts",
                "chart_id": chart_id,
            },
        )

    result = build_remove_chart(chart_id, active_chart)
    return _success_detail(tool_call_id, "remove_chart", result)


def _dispatch_widget_tool(
    name: str,
    arguments: dict[str, Any],
    tool_call_id: str,
    active_widgets_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    builder = WIDGET_BUILDERS.get(name)
    if builder is None:
        return _error_detail(
            tool_call_id,
            name,
            {"ok": False, "error_type": "unknown_tool", "message": f"Неизвестный widget-инструмент: {name}"},
        )

    payload = dict(arguments)
    widget_id = str(payload.pop("widget_id", "") or "").strip()
    expected_type = WIDGET_TYPE_BY_TOOL[name]

    if widget_id:
        active_widget = active_widgets_by_id.get(widget_id)
        if active_widget is None:
            return _error_detail(
                tool_call_id,
                name,
                {
                    "ok": False,
                    "error_type": "widget_not_found",
                    "message": f"Виджет widget_id={widget_id!r} не найден среди active_widgets",
                    "widget_id": widget_id,
                },
            )
        if active_widget.get("widget_type") != expected_type:
            return _error_detail(
                tool_call_id,
                name,
                {
                    "ok": False,
                    "error_type": "widget_type_mismatch",
                    "message": (
                        f"Виджет {widget_id!r} имеет тип {active_widget.get('widget_type')!r}, "
                        f"а tool {name} создаёт {expected_type!r}"
                    ),
                    "widget_id": widget_id,
                },
            )
    else:
        widget_id = str(uuid.uuid4())

    result = builder(payload)
    if result.get("ok", False):
        result["widget_id"] = widget_id
        return _success_detail(tool_call_id, name, result)
    return _error_detail(tool_call_id, name, result)


def _call_with_autocreate(chat_id: str, action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return action()
    except SandboxServiceError as error:
        if error.payload.get("error_type") != "sandbox_not_ready":
            raise
        create_sandbox(chat_id)
        return action()


def _dispatch_sandbox_tool(chat_id: str, name: str, arguments: dict[str, Any], tool_call_id: str) -> dict[str, Any]:
    try:
        if name == "create_sandbox":
            result = create_sandbox(chat_id)
            return _success_detail(tool_call_id, name, result)

        if name == "run_python":
            code = arguments.get("code", "").strip()
            if not code:
                raise ValueError("run_python требует code")
            result = _call_with_autocreate(chat_id, lambda: run_python(chat_id, code))
            if result.get("ok", False):
                return _success_detail(tool_call_id, name, result)
            return _error_detail(tool_call_id, name, result)

        if name == "save_sql_to_sandbox":
            sql = arguments.get("sql", "").strip()
            filename = arguments.get("filename", "").strip()
            file_format = arguments.get("format", "").strip()
            if not sql or not filename or not file_format:
                raise ValueError("save_sql_to_sandbox требует sql, filename, format")
            result = _call_with_autocreate(
                chat_id, lambda: save_sql_to_sandbox(chat_id, sql, filename, file_format)
            )
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


def _iterations_exhausted_error(tool_call_id: str, name: str) -> dict[str, Any]:
    return _error_detail(
        tool_call_id,
        name,
        {
            "ok": False,
            "error_type": "iterations_exhausted",
            "message": ITERATIONS_EXHAUSTED_TOOL_MESSAGE,
        },
    )


def _execute_one(
    chat_id: str,
    tool_call: dict[str, Any],
    active_charts_by_id: dict[str, dict[str, Any]],
    active_widgets_by_id: dict[str, dict[str, Any]],
    iterations_exhausted: bool = False,
) -> dict[str, Any]:
    tool_call_id = tool_call.get("id") or "unknown"
    name, arguments, parse_error = _parse_tool_arguments(tool_call)
    if parse_error is not None:
        return _error_detail(tool_call_id, name, parse_error)

    if iterations_exhausted and name not in CHART_RENDER_TOOL_NAMES:
        return _iterations_exhausted_error(tool_call_id, name)

    if name == "execute_sql":
        sql = arguments.get("sql", "").strip()
        if not sql:
            return _error_detail(
                tool_call_id,
                name,
                {"ok": False, "error_type": "invalid_arguments", "message": "execute_sql требует sql"},
            )
        return _run_single_sql(tool_call_id, sql)

    if name == "remove_chart":
        return _dispatch_remove_chart(arguments, tool_call_id, active_charts_by_id)

    if name in CHART_BUILDERS:
        return _dispatch_chart_tool(name, arguments, tool_call_id, active_charts_by_id)

    if name in WIDGET_TOOL_NAMES:
        return _dispatch_widget_tool(name, arguments, tool_call_id, active_widgets_by_id)

    if name in SANDBOX_TOOL_NAMES:
        return _dispatch_sandbox_tool(chat_id, name, arguments, tool_call_id)

    return _error_detail(
        tool_call_id,
        name,
        {"ok": False, "error_type": "unknown_tool", "message": f"Неизвестный инструмент: {name}"},
    )


def _safe_execute_one(
    chat_id: str,
    tool_call: dict[str, Any],
    active_charts_by_id: dict[str, dict[str, Any]],
    active_widgets_by_id: dict[str, dict[str, Any]],
    iterations_exhausted: bool = False,
) -> dict[str, Any]:
    tool_call_id = tool_call.get("id") or "unknown"
    name = _tool_name(tool_call)
    try:
        return _execute_one(
            chat_id,
            tool_call,
            active_charts_by_id,
            active_widgets_by_id,
            iterations_exhausted,
        )
    except Exception as error:
        return _error_detail(
            tool_call_id,
            name,
            {
                "ok": False,
                "error_type": "tool_execution_error",
                "message": str(error),
            },
        )


def execute_tool_calls(tool_calls: list[dict[str, Any]], chat_id: str) -> list[dict[str, Any]]:
    detailed = execute_tool_calls_detailed(tool_calls, chat_id)
    return [item["message"] for item in detailed]


def execute_tool_calls_detailed(
    tool_calls: list[dict[str, Any]],
    chat_id: str,
    active_charts_by_id: dict[str, dict[str, Any]] | None = None,
    active_widgets_by_id: dict[str, dict[str, Any]] | None = None,
    iterations_exhausted: bool = False,
) -> list[dict[str, Any]]:
    if not tool_calls:
        return []

    if len(tool_calls) > MAX_PARALLEL_QUERIES:
        return _tool_batch_error(
            tool_calls,
            "tool_limit_exceeded",
            (
                f"Too many tool calls in one step ({len(tool_calls)}). "
                f"Maximum is {MAX_PARALLEL_QUERIES}. "
                f"Retry with at most {MAX_PARALLEL_QUERIES} tools per step."
            ),
        )

    try:
        return _execute_tool_calls_detailed(
            tool_calls,
            chat_id,
            active_charts_by_id or {},
            active_widgets_by_id or {},
            iterations_exhausted,
        )
    except Exception as error:
        return _tool_batch_error(
            tool_calls,
            "tool_execution_error",
            str(error),
        )


def _execute_tool_calls_detailed(
    tool_calls: list[dict[str, Any]],
    chat_id: str,
    charts_by_id: dict[str, dict[str, Any]],
    widgets_by_id: dict[str, dict[str, Any]],
    iterations_exhausted: bool = False,
) -> list[dict[str, Any]]:
    has_local = any(_tool_name(tool_call) in LOCAL_TOOL_NAMES for tool_call in tool_calls)
    has_sql = any(_tool_name(tool_call) == "execute_sql" for tool_call in tool_calls)

    if has_local:
        return [
            _safe_execute_one(chat_id, tool_call, charts_by_id, widgets_by_id, iterations_exhausted)
            for tool_call in tool_calls
        ]

    if not has_sql:
        return [
            _safe_execute_one(chat_id, tool_call, charts_by_id, widgets_by_id, iterations_exhausted)
            for tool_call in tool_calls
        ]

    prepared = [tool_call for tool_call in tool_calls if _tool_name(tool_call) == "execute_sql"]
    if len(prepared) != len(tool_calls):
        return [
            _safe_execute_one(chat_id, tool_call, charts_by_id, widgets_by_id, iterations_exhausted)
            for tool_call in tool_calls
        ]

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(len(prepared), MAX_PARALLEL_QUERIES)) as executor:
        futures = {}
        for tool_call in prepared:
            future = executor.submit(
                _safe_execute_one,
                chat_id,
                tool_call,
                charts_by_id,
                widgets_by_id,
                iterations_exhausted,
            )
            futures[future] = tool_call["id"]
        for future in as_completed(futures):
            results.append(future.result())

    order = {tool_call["id"]: index for index, tool_call in enumerate(tool_calls)}
    results.sort(key=lambda item: order[item["tool_call_id"]])
    return results
