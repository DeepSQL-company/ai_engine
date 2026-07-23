from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.main_agent.config import MAX_RESTORE_CONTEXT_BYTES


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


class CanonicalFunction(BaseModel):
    name: str = Field(min_length=1)
    arguments: str

    model_config = ConfigDict(extra="forbid")


class CanonicalToolCall(BaseModel):
    id: str = Field(min_length=1)
    type: Literal["function"]
    function: CanonicalFunction

    model_config = ConfigDict(extra="forbid")


class CanonicalMessage(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[CanonicalToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_role_fields(self) -> "CanonicalMessage":
        if self.role == "user":
            if not self.content or self.tool_calls or self.tool_call_id or self.name:
                raise ValueError("invalid canonical user message")
        elif self.role == "assistant":
            if self.tool_call_id or self.name or (not self.content and not self.tool_calls):
                raise ValueError("invalid canonical assistant message")
        elif (
            not self.content
            or not self.tool_call_id
            or not self.name
            or self.tool_calls
        ):
            raise ValueError("invalid canonical tool message")
        return self


class RestoreContext(BaseModel):
    schema_version: Literal[1]
    conversation_id: UUID
    revision: int = Field(ge=0)
    summary: str = ""
    messages: list[CanonicalMessage]
    summarized_through_turn_id: UUID | None = None
    latest_included_turn_id: UUID | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_sequence(self) -> "RestoreContext":
        if self.messages and self.messages[0].role != "user":
            raise ValueError("canonical context must start with a user message")
        pending: dict[str, str] = {}
        for message in self.messages:
            if message.role == "assistant" and message.tool_calls:
                if pending:
                    raise ValueError("nested canonical tool calls")
                pending = {call.id: call.function.name for call in message.tool_calls}
            elif message.role == "tool":
                if pending.get(message.tool_call_id or "") != message.name:
                    raise ValueError("unmatched canonical tool message")
                pending.pop(message.tool_call_id or "", None)
            elif pending:
                raise ValueError("canonical tool calls must be completed")
        if pending:
            raise ValueError("canonical tool calls must be completed")
        if len(self.model_dump_json().encode()) > MAX_RESTORE_CONTEXT_BYTES:
            raise ValueError("restore context exceeds configured limit")
        return self


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
    restore_context: RestoreContext | None = Field(
        default=None,
        description="Trusted service-to-service context used after an agent restart.",
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
