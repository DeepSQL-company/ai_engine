import logging

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from services.common.api_auth import apply_openapi_api_key, install_api_key_middleware
from services.common.openapi import DOCS_PUBLIC_PATHS, swagger_kwargs
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

API_DESCRIPTION = """
## Что это

HTTP-API SQL-агента: принимает текстовый вопрос, ходит в PostgreSQL (read-only), при необходимости
запускает Python в песочнице и отдаёт ответ **потоком SSE** (`text/event-stream`).

## Авторизация

Все рабочие эндпоинты (кроме `/health` и этой документации) требуют ключ:

- заголовок **`X-API-Key: <ваш ключ>`**, или
- **`Authorization: Bearer <ваш ключ>`**

В Swagger нажми **Authorize** и вставь ключ — тогда можно дернуть `/chat` из браузера.

## Как пользоваться `/chat`

1. `POST /chat` с телом `{"message": "..."}`.
2. Читай SSE: каждая строка `event: <тип>` + `data: <json>`.
3. Сохрани `chat_id` из первого события `chat` — передай его в следующих запросах для контекста.

## Основные SSE-события

| event | Зачем |
|-------|--------|
| `chat` | ID чата, новый или продолжение |
| `metadata` | Схема БД, которую агент подставил в промпт |
| `reasoning_delta` / `content_delta` | Стрим мыслей и текста ответа |
| `tool_start` / `tool_result` | Вызов tool (SQL, sandbox, chart, widget) и результат |
| `assistant_message` | Финальный текст ассистента за итерацию |
| `error` | Ошибка (LLM, SQL, sandbox…) |
| `done` | Конец turn: счётчики итераций и SQL |

Chart-tools возвращают JSON с `result.kind = "chart"` — график рисует **клиент**, не сервер.
Widget-tools возвращают JSON с `result.kind = "widget"` — KPI, insight, data quality и table рендерит **клиент**.

## Лимиты

Размер ответа SQL, число итераций агента, chart points и т.д. задаются переменными окружения сервиса
(`MAX_QUERY_RESULT_CHARS`, `MAX_AGENT_ITERATIONS`, …).
"""

app = FastAPI(
    **swagger_kwargs(
        title="DeepSQL Agent API",
        description=API_DESCRIPTION,
        tags=[
            {"name": "health", "description": "Жив ли процесс. Ключ не нужен."},
            {"name": "agent", "description": "Диалог с агентом. Ответ — SSE-поток, нужен API key."},
        ],
    )
)

install_api_key_middleware(app, API_KEY, public_paths=frozenset({"/health"}) | DOCS_PUBLIC_PATHS)
if API_KEY:
    apply_openapi_api_key(app)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["health"],
    summary="Проверка, что сервис запущен",
    description="Используй для healthcheck и мониторинга. **API key не нужен.**",
)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=APP_TITLE)


@app.post(
    "/chat",
    tags=["agent"],
    summary="Отправить сообщение агенту",
    description=(
        "Главный эндпоинт. **Нужен API key.**\n\n"
        "Ответ — не JSON, а **SSE-поток** (`Content-Type: text/event-stream`). "
        "Парси построчно: `event:` — имя события, `data:` — JSON с полем `type`.\n\n"
        f"Полный список типов: `{', '.join(SSE_EVENT_TYPES)}`.\n\n"
        "**Multi-turn:** передай `chat_id` из первого ответа — история хранится в памяти процесса "
        "(пропадёт при рестарте контейнера).\n\n"
        "**Charts:** в `tool_result` смотри `result.kind == \"chart\"` и `chart_type` "
        "(gauge, pie, bar, line, scatter) — `spec` отдаётся клиенту для отрисовки. "
        "Удаление: `remove_chart` → `result.action == \"remove\"` и `chart_id`.\n\n"
        "**Widgets:** в `tool_result` смотри `result.kind == \"widget\"` и `widget_type` "
        "(kpi, insight, data_quality, table) — `spec` отдаётся клиенту для рендера.\n\n"
        "**Dashboard state:** передай `active_charts` и `active_widgets`, чтобы агент мог обновлять "
        "существующие элементы по `chart_id` / `widget_id`.\n\n"
        "**curl:** `curl -N -H 'X-API-Key: ...' -H 'Content-Type: application/json' "
        "-d '{\"message\":\"...\"}' https://host/chat`"
    ),
    responses={
        200: {
            "description": "SSE-поток: события агента до `done` или `error`",
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "example": (
                        'event: chat\n'
                        'data: {"type":"chat","chat_id":"054256de-...","is_new":true,"history_messages_count":0}\n\n'
                        'event: content_delta\n'
                        'data: {"type":"content_delta","content":"4","iteration":1,"chat_id":"054256de-..."}\n\n'
                        'event: assistant_message\n'
                        'data: {"type":"assistant_message","content":"4","iteration":1,"chat_id":"054256de-..."}\n\n'
                        'event: done\n'
                        'data: {"type":"done","iterations":1,"sql_calls_count":0,"tool_calls_count":0,"chat_id":"054256de-..."}\n\n'
                    ),
                }
            },
        },
        401: {"description": "Нет или неверный `X-API-Key` / Bearer token"},
        503: {"description": "На сервере не задан `API_KEY`"},
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
            for event in stream_agent(
                session.messages,
                chat_id,
                [chart.model_dump() for chart in request.active_charts],
                [widget.model_dump() for widget in request.active_widgets],
            ):
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
