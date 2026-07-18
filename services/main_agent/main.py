import logging

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from services.common.api_auth import apply_openapi_api_key, install_api_key_middleware
from services.common.openapi import swagger_kwargs
from services.main_agent.agent import AgentError, stream_agent
from services.main_agent.chat_store import chat_store
from services.main_agent.config import API_KEY, APP_TITLE, HOST, PORT
from services.main_agent.models import ChatRequest, HealthResponse
from services.main_agent.sse_events import format_sse

logging.basicConfig(level=logging.INFO)

SSE_EVENT_TYPES = [
    "chat",
    "status",
    "metadata",
    "iteration_start",
    "reasoning_delta",
    "content_delta",
    "reasoning",
    "assistant_message",
    "tool_start",
    "tool_result",
    "answer",
    "error",
    "done",
]

app = FastAPI(
    **swagger_kwargs(
        title=APP_TITLE,
        description=(
            "SQL-агент с LLM: SSE-стрим `/chat`, tool calls (SQL, sandbox, charts), "
            "multi-turn через chat_id."
        ),
        tags=[
            {"name": "health", "description": "Проверка состояния сервиса"},
            {"name": "agent", "description": "Диалог с агентом"},
        ],
    )
)

install_api_key_middleware(app, API_KEY)
if API_KEY:
    apply_openapi_api_key(app)


@app.get("/health", response_model=HealthResponse, tags=["health"], summary="Health check")
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=APP_TITLE)


@app.post(
    "/chat",
    tags=["agent"],
    summary="Диалог с агентом (SSE)",
    description=(
        "Возвращает поток Server-Sent Events (`text/event-stream`). "
        "Каждое событие — JSON в поле `data`, тип в `event`. "
        f"Типы событий: {', '.join(SSE_EVENT_TYPES)}. "
        "Chart JSON приходит в `tool_result` с `result.kind=chart`."
    ),
    responses={
        200: {
            "description": "SSE-поток событий агента",
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "example": (
                        'event: chat\n'
                        'data: {"type":"chat","chat_id":"...","is_new":true}\n\n'
                        'event: tool_result\n'
                        'data: {"type":"tool_result","name":"render_pie_chart","success":true,'
                        '"result":{"ok":true,"kind":"chart","chart_type":"pie","spec":{...}}}\n\n'
                        'event: done\n'
                        'data: {"type":"done","iterations":3,"sql_calls_count":1}\n\n'
                    ),
                }
            },
        }
    },
)
def chat(request: ChatRequest) -> StreamingResponse:
    chat_id, session, is_new = chat_store.get_or_create(request.chat_id)
    history_messages_count = len(session.messages)
    chat_store.append_user_message(chat_id, request.message)
    turn_start_index = len(session.messages) - 1

    def event_generator():
        yield format_sse(
            {
                "type": "chat",
                "chat_id": chat_id,
                "is_new": is_new,
                "history_messages_count": history_messages_count,
            }
        )

        try:
            for event in stream_agent(session.messages, chat_id):
                event["chat_id"] = chat_id
                yield format_sse(event)
        except AgentError as error:
            del session.messages[turn_start_index:]
            yield format_sse({"type": "error", "chat_id": chat_id, "message": str(error)})
        except Exception as error:
            del session.messages[turn_start_index:]
            yield format_sse({"type": "error", "chat_id": chat_id, "message": str(error)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    uvicorn.run("services.main_agent.main:app", host=HOST, port=PORT, reload=False)
