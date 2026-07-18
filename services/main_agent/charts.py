from typing import Any

from services.main_agent.config import MAX_CHART_POINTS, MAX_CHART_SERIES, MAX_PIE_SLICES


class ChartValidationError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _chart_payload(chart_type: str, title: str, spec: dict[str, Any], description: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "kind": "chart",
        "chart_type": chart_type,
        "title": title,
        "spec": spec,
    }
    if description:
        payload["description"] = description
    return payload


def _chart_error(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error_type": "chart_validation_error",
        "message": message,
    }


def _require_title(title: str) -> str:
    value = title.strip()
    if not value:
        raise ChartValidationError("title обязателен")
    return value


def _as_number(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ChartValidationError(f"{field} должно быть числом") from error


def build_gauge(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        title = _require_title(arguments.get("title", ""))
        value = _as_number(arguments.get("value"), "value")
        minimum = _as_number(arguments.get("min", 0), "min")
        maximum = _as_number(arguments.get("max", 100), "max")
        if maximum <= minimum:
            raise ChartValidationError("max должно быть больше min")

        unit = (arguments.get("unit") or "").strip() or None
        spec: dict[str, Any] = {
            "value": value,
            "min": minimum,
            "max": maximum,
        }
        if unit:
            spec["unit"] = unit
        if arguments.get("thresholds"):
            spec["thresholds"] = arguments["thresholds"]

        return _chart_payload("gauge", title, spec, arguments.get("description"))
    except ChartValidationError as error:
        return _chart_error(error.message)


def build_pie_chart(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        title = _require_title(arguments.get("title", ""))
        slices = arguments.get("slices")
        if not isinstance(slices, list) or not slices:
            raise ChartValidationError("slices должен быть непустым массивом")
        if len(slices) > MAX_PIE_SLICES:
            raise ChartValidationError(f"Максимум {MAX_PIE_SLICES} секторов")

        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(slices):
            if not isinstance(item, dict):
                raise ChartValidationError(f"slices[{index}] должен быть объектом")
            label = str(item.get("label", "")).strip()
            if not label:
                raise ChartValidationError(f"slices[{index}].label обязателен")
            value = _as_number(item.get("value"), f"slices[{index}].value")
            normalized.append({"label": label, "value": value})

        return _chart_payload(
            "pie",
            title,
            {"slices": normalized},
            arguments.get("description"),
        )
    except ChartValidationError as error:
        return _chart_error(error.message)


def _normalize_series(arguments: dict[str, Any], categories: list[Any]) -> list[dict[str, Any]]:
    series = arguments.get("series")
    if not isinstance(series, list) or not series:
        raise ChartValidationError("series должен быть непустым массивом")
    if len(series) > MAX_CHART_SERIES:
        raise ChartValidationError(f"Максимум {MAX_CHART_SERIES} серий")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(series):
        if not isinstance(item, dict):
            raise ChartValidationError(f"series[{index}] должен быть объектом")
        name = str(item.get("name", "")).strip()
        if not name:
            raise ChartValidationError(f"series[{index}].name обязателен")
        values = item.get("values")
        if not isinstance(values, list) or not values:
            raise ChartValidationError(f"series[{index}].values должен быть непустым массивом")
        if len(values) != len(categories):
            raise ChartValidationError(
                f"series[{index}].values должен иметь длину {len(categories)} как categories"
            )
        numeric_values = [_as_number(value, f"series[{index}].values[{pos}]") for pos, value in enumerate(values)]
        normalized.append({"name": name, "values": numeric_values})
    return normalized


def build_bar_chart(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        title = _require_title(arguments.get("title", ""))
        categories = arguments.get("categories")
        if not isinstance(categories, list) or not categories:
            raise ChartValidationError("categories должен быть непустым массивом")
        if len(categories) > MAX_CHART_POINTS:
            raise ChartValidationError(f"Максимум {MAX_CHART_POINTS} категорий")

        normalized_categories = [str(item) for item in categories]
        series = _normalize_series(arguments, normalized_categories)
        spec: dict[str, Any] = {
            "categories": normalized_categories,
            "series": series,
            "orientation": arguments.get("orientation", "vertical"),
        }
        return _chart_payload("bar", title, spec, arguments.get("description"))
    except ChartValidationError as error:
        return _chart_error(error.message)


def build_line_chart(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        title = _require_title(arguments.get("title", ""))
        categories = arguments.get("categories")
        if not isinstance(categories, list) or not categories:
            raise ChartValidationError("categories должен быть непустым массивом")
        if len(categories) > MAX_CHART_POINTS:
            raise ChartValidationError(f"Максимум {MAX_CHART_POINTS} точек")

        normalized_categories = [str(item) for item in categories]
        series = _normalize_series(arguments, normalized_categories)
        return _chart_payload(
            "line",
            title,
            {"categories": normalized_categories, "series": series},
            arguments.get("description"),
        )
    except ChartValidationError as error:
        return _chart_error(error.message)


def build_scatter_chart(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        title = _require_title(arguments.get("title", ""))
        points = arguments.get("points")
        if not isinstance(points, list) or not points:
            raise ChartValidationError("points должен быть непустым массивом")
        if len(points) > MAX_CHART_POINTS:
            raise ChartValidationError(f"Максимум {MAX_CHART_POINTS} точек")

        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(points):
            if not isinstance(item, dict):
                raise ChartValidationError(f"points[{index}] должен быть объектом")
            point = {
                "x": _as_number(item.get("x"), f"points[{index}].x"),
                "y": _as_number(item.get("y"), f"points[{index}].y"),
            }
            label = str(item.get("label", "")).strip()
            if label:
                point["label"] = label
            normalized.append(point)

        spec: dict[str, Any] = {"points": normalized}
        x_label = (arguments.get("x_label") or "").strip()
        y_label = (arguments.get("y_label") or "").strip()
        if x_label:
            spec["x_label"] = x_label
        if y_label:
            spec["y_label"] = y_label

        return _chart_payload("scatter", title, spec, arguments.get("description"))
    except ChartValidationError as error:
        return _chart_error(error.message)


CHART_BUILDERS = {
    "render_gauge": build_gauge,
    "render_pie_chart": build_pie_chart,
    "render_bar_chart": build_bar_chart,
    "render_line_chart": build_line_chart,
    "render_scatter_chart": build_scatter_chart,
}
