import json
from typing import Any

from services.main_agent.config import (
    MAX_DATA_QUALITY_CHECKS,
    MAX_INSIGHT_POINTS,
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
)

WIDGET_TYPE_BY_TOOL = {
    "render_kpi": "kpi",
    "render_insight": "insight",
    "render_data_quality": "data_quality",
    "render_table": "table",
}

STATUS_VALUES = {"good", "warning", "critical", "neutral", "info"}
CHANGE_DIRECTIONS = {"up", "down", "flat"}
CONFIDENCE_VALUES = {"high", "medium", "low"}
COLUMN_FORMATS = {"text", "number", "currency", "percent", "date", "datetime"}
SORT_DIRECTIONS = {"asc", "desc"}


class WidgetValidationError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _widget_payload(
    widget_type: str,
    title: str,
    spec: dict[str, Any],
    description: str | None = None,
    widget_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "kind": "widget",
        "widget_id": widget_id,
        "widget_type": widget_type,
        "title": title,
        "spec": spec,
    }
    if description:
        payload["description"] = description
    return payload


def _widget_error(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error_type": "widget_validation_error",
        "message": message,
    }


def format_active_widgets_for_prompt(active_widgets: list[dict[str, Any]]) -> str:
    if not active_widgets:
        return "Нет активных виджетов на экране клиента."

    lines: list[str] = []
    for widget in active_widgets:
        lines.append(
            json.dumps(
                {
                    "widget_id": widget["widget_id"],
                    "widget_type": widget["widget_type"],
                    "title": widget["title"],
                    "description": widget.get("description"),
                    "spec": widget.get("spec", {}),
                },
                ensure_ascii=False,
                default=str,
            )
        )
    return "\n".join(lines)


def _require_title(title: str) -> str:
    value = title.strip()
    if not value:
        raise WidgetValidationError("title обязателен")
    return value


def _require_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WidgetValidationError(f"{field} обязателен")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _as_number(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise WidgetValidationError(f"{field} должно быть числом") from error


def _require_status(value: Any, field: str) -> str:
    status = str(value or "").strip()
    if status not in STATUS_VALUES:
        raise WidgetValidationError(f"{field} должно быть одним из: {', '.join(sorted(STATUS_VALUES))}")
    return status


def _normalize_change(change: Any) -> dict[str, Any] | None:
    if change is None:
        return None
    if not isinstance(change, dict):
        raise WidgetValidationError("change должен быть объектом")

    normalized: dict[str, Any] = {
        "value": _as_number(change.get("value"), "change.value"),
    }
    direction = str(change.get("direction", "")).strip()
    if direction:
        if direction not in CHANGE_DIRECTIONS:
            raise WidgetValidationError(f"change.direction должно быть одним из: {', '.join(sorted(CHANGE_DIRECTIONS))}")
        normalized["direction"] = direction
    unit = _optional_text(change.get("unit"))
    if unit:
        normalized["unit"] = unit
    label = _optional_text(change.get("label"))
    if label:
        normalized["label"] = label
    return normalized


def build_kpi(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        title = _require_title(arguments.get("title", ""))
        value = _as_number(arguments.get("value"), "value")
        spec: dict[str, Any] = {"value": value}

        unit = _optional_text(arguments.get("unit"))
        if unit:
            spec["unit"] = unit
        period = _optional_text(arguments.get("period"))
        if period:
            spec["period"] = period
        label = _optional_text(arguments.get("label"))
        if label:
            spec["label"] = label
        if arguments.get("change") is not None:
            spec["change"] = _normalize_change(arguments.get("change"))
        if arguments.get("status") is not None:
            spec["status"] = _require_status(arguments.get("status"), "status")

        return _widget_payload("kpi", title, spec, arguments.get("description"))
    except WidgetValidationError as error:
        return _widget_error(error.message)


def build_insight(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        title = _require_title(arguments.get("title", ""))
        summary = _require_text(arguments.get("summary"), "summary")
        points_raw = arguments.get("points")
        if not isinstance(points_raw, list) or not points_raw:
            raise WidgetValidationError("points должен быть непустым массивом")
        if len(points_raw) > MAX_INSIGHT_POINTS:
            raise WidgetValidationError(f"Максимум {MAX_INSIGHT_POINTS} пунктов в points")

        points: list[dict[str, Any]] = []
        for index, item in enumerate(points_raw):
            if not isinstance(item, dict):
                raise WidgetValidationError(f"points[{index}] должен быть объектом")
            text = _require_text(item.get("text"), f"points[{index}].text")
            point: dict[str, Any] = {"text": text}
            evidence = _optional_text(item.get("evidence"))
            if evidence:
                point["evidence"] = evidence
            points.append(point)

        spec: dict[str, Any] = {
            "summary": summary,
            "points": points,
        }
        period = _optional_text(arguments.get("period"))
        if period:
            spec["period"] = period
        if arguments.get("confidence") is not None:
            confidence = str(arguments.get("confidence", "")).strip()
            if confidence not in CONFIDENCE_VALUES:
                raise WidgetValidationError(
                    f"confidence должно быть одним из: {', '.join(sorted(CONFIDENCE_VALUES))}"
                )
            spec["confidence"] = confidence

        return _widget_payload("insight", title, spec, arguments.get("description"))
    except WidgetValidationError as error:
        return _widget_error(error.message)


def _normalize_check(index: int, item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise WidgetValidationError(f"checks[{index}] должен быть объектом")

    name = _require_text(item.get("name"), f"checks[{index}].name")
    label = _require_text(item.get("label"), f"checks[{index}].label")
    status = _require_status(item.get("status"), f"checks[{index}].status")
    check: dict[str, Any] = {
        "name": name,
        "label": label,
        "status": status,
    }
    value = _optional_text(item.get("value"))
    if value:
        check["value"] = value
    detail = _optional_text(item.get("detail"))
    if detail:
        check["detail"] = detail
    return check


def build_data_quality(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        title = _require_title(arguments.get("title", ""))
        status = _require_status(arguments.get("status"), "status")
        checks_raw = arguments.get("checks")
        if not isinstance(checks_raw, list) or not checks_raw:
            raise WidgetValidationError("checks должен быть непустым массивом")
        if len(checks_raw) > MAX_DATA_QUALITY_CHECKS:
            raise WidgetValidationError(f"Максимум {MAX_DATA_QUALITY_CHECKS} проверок")

        checks = [_normalize_check(index, item) for index, item in enumerate(checks_raw)]
        spec: dict[str, Any] = {
            "status": status,
            "checks": checks,
        }

        freshness = arguments.get("freshness")
        if freshness is not None:
            if not isinstance(freshness, dict):
                raise WidgetValidationError("freshness должен быть объектом")
            freshness_label = _require_text(freshness.get("label"), "freshness.label")
            freshness_value = _require_text(freshness.get("value"), "freshness.value")
            freshness_payload: dict[str, Any] = {
                "label": freshness_label,
                "value": freshness_value,
            }
            if freshness.get("status") is not None:
                freshness_payload["status"] = _require_status(freshness.get("status"), "freshness.status")
            spec["freshness"] = freshness_payload

        return _widget_payload("data_quality", title, spec, arguments.get("description"))
    except WidgetValidationError as error:
        return _widget_error(error.message)


def _normalize_columns(columns_raw: Any) -> list[dict[str, Any]]:
    if not isinstance(columns_raw, list) or not columns_raw:
        raise WidgetValidationError("columns должен быть непустым массивом")
    if len(columns_raw) > MAX_TABLE_COLUMNS:
        raise WidgetValidationError(f"Максимум {MAX_TABLE_COLUMNS} колонок")

    columns: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, item in enumerate(columns_raw):
        if not isinstance(item, dict):
            raise WidgetValidationError(f"columns[{index}] должен быть объектом")
        key = _require_text(item.get("key"), f"columns[{index}].key")
        if key in keys:
            raise WidgetValidationError(f"columns[{index}].key дублирует key={key!r}")
        keys.add(key)
        label = _require_text(item.get("label"), f"columns[{index}].label")
        column: dict[str, Any] = {"key": key, "label": label}
        column_format = str(item.get("format", "text")).strip() or "text"
        if column_format not in COLUMN_FORMATS:
            raise WidgetValidationError(
                f"columns[{index}].format должно быть одним из: {', '.join(sorted(COLUMN_FORMATS))}"
            )
        column["format"] = column_format
        columns.append(column)
    return columns


def _normalize_rows(rows_raw: Any, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(rows_raw, list) or not rows_raw:
        raise WidgetValidationError("rows должен быть непустым массивом")
    if len(rows_raw) > MAX_TABLE_ROWS:
        raise WidgetValidationError(f"Максимум {MAX_TABLE_ROWS} строк")

    column_keys = [column["key"] for column in columns]
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(rows_raw):
        if not isinstance(item, dict):
            raise WidgetValidationError(f"rows[{index}] должен быть объектом")
        row: dict[str, Any] = {}
        for key in column_keys:
            if key not in item:
                raise WidgetValidationError(f"rows[{index}] не содержит колонку {key!r}")
            row[key] = item[key]
        rows.append(row)
    return rows


def build_table(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        title = _require_title(arguments.get("title", ""))
        columns = _normalize_columns(arguments.get("columns"))
        rows = _normalize_rows(arguments.get("rows"), columns)
        spec: dict[str, Any] = {
            "columns": columns,
            "rows": rows,
        }

        sort = arguments.get("sort")
        if sort is not None:
            if not isinstance(sort, dict):
                raise WidgetValidationError("sort должен быть объектом")
            sort_column = _require_text(sort.get("column"), "sort.column")
            column_keys = {column["key"] for column in columns}
            if sort_column not in column_keys:
                raise WidgetValidationError(f"sort.column={sort_column!r} не найден среди columns")
            direction = str(sort.get("direction", "asc")).strip() or "asc"
            if direction not in SORT_DIRECTIONS:
                raise WidgetValidationError(f"sort.direction должно быть одним из: {', '.join(sorted(SORT_DIRECTIONS))}")
            spec["sort"] = {"column": sort_column, "direction": direction}

        return _widget_payload("table", title, spec, arguments.get("description"))
    except WidgetValidationError as error:
        return _widget_error(error.message)


WIDGET_BUILDERS = {
    "render_kpi": build_kpi,
    "render_insight": build_insight,
    "render_data_quality": build_data_quality,
    "render_table": build_table,
}
