from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, description="Сообщение пользователя")
    chat_id: str | None = Field(
        default=None,
        description="ID чата для multi-turn диалога. Если не передан — создаётся новый.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Посчитай количество рейсов по статусам и построй pie chart.",
                "chat_id": None,
            }
        }
    )


class HealthResponse(BaseModel):
    status: str
    service: str
