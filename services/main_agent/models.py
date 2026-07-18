from pydantic import BaseModel, ConfigDict, Field


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
