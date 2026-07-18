# API

Все эндпоинты (кроме `/health`) требуют заголовок:

```
X-API-Key: <API_KEY из .env>
```

или `Authorization: Bearer <API_KEY>`.

Переменная окружения: `API_KEY`.

---

## main_agent — `:8002`

Swagger: http://localhost:8002/docs

### `GET /health`

```json
{ "status": "ok", "service": "main_agent" }
```

### `POST /chat`

Диалог с агентом. Ответ — SSE (`text/event-stream`).

**Request**

```json
{
  "message": "string",
  "chat_id": "string | null"
}
```

- `chat_id: null` — новый чат
- `chat_id: "..."` — продолжение диалога

**SSE**

```
event: <type>
data: <JSON>

```

| type | data |
|---|---|
| `chat` | `{ "chat_id", "is_new", "history_messages_count" }` |
| `status` | `{ "stage", "message" }` |
| `metadata` | `{ "content", "length" }` |
| `iteration_start` | `{ "iteration" }` |
| `reasoning_delta` | `{ "iteration", "content" }` |
| `content_delta` | `{ "iteration", "content" }` |
| `reasoning` | `{ "iteration", "content" }` |
| `assistant_message` | `{ "iteration", "content" }` |
| `tool_start` | `{ "iteration", "tool_call_id", "name", "input" }` |
| `tool_result` | см. ниже |
| `answer` | `{ "content" }` |
| `error` | `{ "message" }` |
| `done` | `{ "sql_calls_count", "tool_calls_count", "iterations", "turn_messages_count", "history_messages_count" }` |

Во всех событиях есть `chat_id`.

#### `tool_result`

```json
{
  "type": "tool_result",
  "iteration": 1,
  "tool_call_id": "...",
  "name": "execute_sql | create_sandbox | save_sql_to_sandbox | run_python | list_sandbox_files | render_gauge | render_pie_chart | render_bar_chart | render_line_chart | render_scatter_chart",
  "success": true,
  "result": {},
  "sql": "...",
  "chart_type": "pie"
}
```

`sql` — только для SQL-tools.  
`chart_type` — только если `result.kind === "chart"`.

**SQL** (`execute_sql`, `success: true`):

```json
{
  "ok": true,
  "columns": ["col1"],
  "rows": [{ "col1": "value" }],
  "row_count": 1,
  "total_row_count": 1,
  "truncated": false,
  "note": null
}
```

**Chart** (`result.kind: "chart"`):

```json
{
  "ok": true,
  "kind": "chart",
  "chart_type": "gauge | pie | bar | line | scatter",
  "title": "...",
  "description": "...",
  "spec": {}
}
```

| chart_type | spec |
|---|---|
| `gauge` | `{ "value", "min", "max", "unit"? }` |
| `pie` | `{ "slices": [{ "label", "value" }] }` |
| `bar` | `{ "categories", "series": [{ "name", "values" }], "orientation"? }` |
| `line` | `{ "categories", "series": [{ "name", "values" }] }` |
| `scatter` | `{ "points": [{ "x", "y", "label"? }], "x_label"?, "y_label"? }` |

**Sandbox** (success):

| name | result |
|---|---|
| `create_sandbox` | `{ "ok", "message", "session_id", "files" }` |
| `save_sql_to_sandbox` | `{ "ok", "message", "filename", "format", "size_bytes", "row_count", "files" }` |
| `run_python` | `{ "ok", "stdout", "stderr", "files" }` |
| `list_sandbox_files` | `{ "ok", "active", "session_id", "files": [{ "name", "size_bytes" }], "max_files", "max_file_bytes" }` |

**Ошибка tool** (`success: false`):

```json
{
  "ok": false,
  "error_type": "sql_error | chart_validation_error | ...",
  "message": "...",
  "hint": "...",
  "sql": "..."
}
```

---

## db_orch — `:8001`

Swagger: http://localhost:8001/docs

### `GET /health`

```json
{ "status": "ok", "service": "db_orch", "db_initialized": true }
```

### `POST /init`

```json
{
  "host": "host.docker.internal",
  "port": 5432,
  "database": "demo",
  "user": "user",
  "password": "user",
  "schema": "bookings"
}
```

```json
{ "status": "ok", "message": "...", "database": "demo" }
```

### `GET /databases`

```json
{ "databases": ["demo"] }
```

### `GET /schemas?database=demo`

```json
{ "schemas": ["bookings", "public"] }
```

### `GET /tables?schema=bookings`

```json
{ "tables": ["flights"] }
```

### `GET /columns?schema=bookings&table=flights`

```json
{
  "columns": [
    { "name": "flight_id", "data_type": "integer", "is_nullable": false, "column_default": null }
  ]
}
```

### `POST /query`

```json
{ "sql": "SELECT 1", "params": null }
```

```json
{
  "ok": true,
  "columns": ["?column?"],
  "rows": [{ "?column?": 1 }],
  "row_count": 1,
  "total_row_count": 1,
  "truncated": false,
  "note": null
}
```

Ошибка — HTTP 400:

```json
{
  "detail": {
    "ok": false,
    "error_type": "sql_error",
    "message": "...",
    "sql": "...",
    "hint": "..."
  }
}
```

### `POST /query/export`

Тело как у `/query`. Лимит ответа до 5MB.
