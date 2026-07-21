from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActiveChart(BaseModel):
    chart_id: str = Field(min_length=1, description="Уникальный id графика на клиенте")
    chart_type: str = Field(
        description="Тип: gauge | pie | bar | line | scatter",
        examples=["pie", "bar"],
    )
    title: str = Field(min_length=1)
    description: str | None = None
    spec: dict[str, Any] = Field(default_factory=dict)


class ActiveWidget(BaseModel):
    widget_id: str = Field(min_length=1, description="Уникальный id виджета на клиенте")
    widget_type: str = Field(
        description="Тип: kpi | insight | data_quality | table",
        examples=["kpi", "table"],
    )
    title: str = Field(min_length=1)
    description: str | None = None
    spec: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    """Тело запроса к агенту."""

    message: str = Field(
        min_length=1,
        description="Вопрос или задача на русском/английском. Агент сам выберет SQL, Python или chart-tools.",
        examples=["Сколько рейсов в таблице flights?", "Построй pie chart по статусам рейсов"],
    )
    chat_id: str | None = Field(
        default=None,
        description=(
            "ID существующего чата для продолжения диалога. "
            "При первом запросе не передавай — возьми chat_id из SSE-события `chat` и подставь в следующие запросы."
        ),
    )
    active_charts: list[ActiveChart] = Field(
        default_factory=list,
        description=(
            "Графики, которые сейчас показаны на экране клиента. "
            "Агент видит их в промпте и может обновить через chart-tool с тем же chart_id."
        ),
    )
    active_widgets: list[ActiveWidget] = Field(
        default_factory=list,
        description=(
            "Виджеты дашборда (KPI, insight, data quality, table), показанные на экране клиента. "
            "Агент видит их в промпте и может обновить через widget-tool с тем же widget_id."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "message": "Посчитай количество рейсов по статусам и построй pie chart.",
                    "chat_id": None,
                },
                {
                    "message": "А сколько из них Arrived?",
                    "chat_id": "054256de-3ffe-4b75-a31e-bcb918a80851",
                },
            ]
        }
    )


class HealthResponse(BaseModel):
    status: str = Field(description="Всегда `ok`, если процесс жив.")
    service: str = Field(description="Имя сервиса, например `main_agent`.")
