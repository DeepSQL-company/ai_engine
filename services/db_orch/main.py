import logging

import uvicorn
from fastapi import FastAPI, HTTPException, Query

from services.common.api_auth import apply_openapi_api_key, install_api_key_middleware
from services.common.openapi import swagger_kwargs
from services.db_orch.config import API_KEY, APP_TITLE, HOST, MAX_EXPORT_RESULT_CHARS, PORT
from services.db_orch.db_manager import DbManager, DbNotInitializedError, DbQueryError, db_manager
from services.db_orch.input_guard import InputValidationError, validate_database_name, validate_pg_identifier
from services.db_orch.models import (
    ColumnsResponse,
    DatabasesResponse,
    DbConnectionConfig,
    HealthResponse,
    InitResponse,
    QueryRequest,
    QueryResponse,
    SchemasResponse,
    TablesResponse,
)

logger = logging.getLogger(__name__)
manager: DbManager = db_manager

app = FastAPI(
    **swagger_kwargs(
        title=APP_TITLE,
        description=(
            "Оркестратор PostgreSQL: инициализация подключения, метаданные схем/таблиц/колонок "
            "и read-only SQL-запросы с лимитом размера ответа."
        ),
        tags=[
            {"name": "health", "description": "Проверка состояния сервиса"},
            {"name": "connection", "description": "Инициализация подключения к БД"},
            {"name": "metadata", "description": "Свежие метаданные PostgreSQL"},
            {"name": "query", "description": "Read-only SQL-запросы"},
        ],
    )
)

install_api_key_middleware(app, API_KEY)
if API_KEY:
    apply_openapi_api_key(app)


def _validation_http_error(error: InputValidationError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"ok": False, "error_type": "validation_error", "message": error.message},
    )


def _parse_database(database: str | None) -> str | None:
    if database is None:
        return None
    try:
        return validate_database_name(database)
    except InputValidationError as error:
        raise _validation_http_error(error) from error


def _parse_schema(schema: str) -> str:
    try:
        return validate_pg_identifier(schema, "schema")
    except InputValidationError as error:
        raise _validation_http_error(error) from error


def _parse_table(table: str) -> str:
    try:
        return validate_pg_identifier(table, "table")
    except InputValidationError as error:
        raise _validation_http_error(error) from error


def _not_initialized_error() -> HTTPException:
    return HTTPException(status_code=400, detail="Сервис не инициализирован. Вызовите POST /init")


@app.get("/health", response_model=HealthResponse, tags=["health"], summary="Health check")
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=APP_TITLE,
        db_initialized=manager.is_initialized,
    )


@app.post(
    "/init",
    response_model=InitResponse,
    tags=["connection"],
    summary="Инициализировать подключение к БД",
    description="Явная инициализация. Без вызова /init остальные эндпоинты вернут 400.",
)
def init_connection(config: DbConnectionConfig | None = None) -> InitResponse:
    try:
        resolved_config = config or manager.load_default_config()
        manager.init(resolved_config)
    except FileNotFoundError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Не удалось подключиться к БД: {error}") from error

    return InitResponse(
        status="ok",
        message="Подключение к БД установлено",
        database=manager.config.database,
    )


@app.get(
    "/databases",
    response_model=DatabasesResponse,
    tags=["metadata"],
    summary="Список баз данных",
)
def get_databases() -> DatabasesResponse:
    try:
        databases = manager.list_databases()
    except DbNotInitializedError:
        raise _not_initialized_error()
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return DatabasesResponse(databases=databases)


@app.get(
    "/schemas",
    response_model=SchemasResponse,
    tags=["metadata"],
    summary="Список схем",
)
def get_schemas(
    database: str | None = Query(default=None, description="Имя БД. По умолчанию — из init"),
) -> SchemasResponse:
    resolved_database = _parse_database(database)
    try:
        schemas = manager.list_schemas(resolved_database)
    except DbNotInitializedError:
        raise _not_initialized_error()
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return SchemasResponse(schemas=schemas)


@app.get(
    "/tables",
    response_model=TablesResponse,
    tags=["metadata"],
    summary="Список таблиц в схеме",
)
def get_tables(
    schema: str = Query(..., description="Имя схемы"),
    database: str | None = Query(default=None, description="Имя БД. По умолчанию — из init"),
) -> TablesResponse:
    resolved_schema = _parse_schema(schema)
    resolved_database = _parse_database(database)
    try:
        tables = manager.list_tables(schema=resolved_schema, database=resolved_database)
    except DbNotInitializedError:
        raise _not_initialized_error()
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return TablesResponse(tables=tables)


@app.get(
    "/columns",
    response_model=ColumnsResponse,
    tags=["metadata"],
    summary="Список колонок таблицы",
)
def get_columns(
    schema: str = Query(..., description="Имя схемы"),
    table: str = Query(..., description="Имя таблицы"),
    database: str | None = Query(default=None, description="Имя БД. По умолчанию — из init"),
) -> ColumnsResponse:
    resolved_schema = _parse_schema(schema)
    resolved_table = _parse_table(table)
    resolved_database = _parse_database(database)
    try:
        columns = manager.list_columns(
            schema=resolved_schema,
            table=resolved_table,
            database=resolved_database,
        )
    except DbNotInitializedError:
        raise _not_initialized_error()
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return ColumnsResponse(columns=columns)


@app.post(
    "/query",
    response_model=QueryResponse,
    tags=["query"],
    summary="Read-only SQL (preview)",
    description="Быстрый preview результата с лимитом символов для агента.",
    responses={
        400: {
            "description": "Ошибка валидации SQL или PostgreSQL",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "ok": False,
                            "error_type": "sql_error",
                            "message": "SQL-запрос завершился ошибкой",
                            "sql": "SELECT ...",
                            "hint": "Проверь имена таблиц и колонок",
                        }
                    }
                }
            },
        }
    },
)
def execute_query(request: QueryRequest) -> QueryResponse:
    try:
        result = manager.execute_query(request.sql, request.params)
    except DbNotInitializedError:
        raise _not_initialized_error()
    except DbQueryError as error:
        raise HTTPException(status_code=400, detail=error.payload) from error
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "error_type": "internal_error", "message": str(error)},
        ) from error

    return QueryResponse(**result)


@app.post(
    "/query/export",
    response_model=QueryResponse,
    tags=["query"],
    summary="Read-only SQL (export)",
    description="Экспорт результата с увеличенным лимитом для sandbox save_sql.",
)
def execute_query_export(request: QueryRequest) -> QueryResponse:
    try:
        result = manager.execute_query(
            request.sql,
            request.params,
            max_result_chars=MAX_EXPORT_RESULT_CHARS,
        )
    except DbNotInitializedError:
        raise _not_initialized_error()
    except DbQueryError as error:
        raise HTTPException(status_code=400, detail=error.payload) from error
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "error_type": "internal_error", "message": str(error)},
        ) from error

    return QueryResponse(**result)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run("services.db_orch.main:app", host=HOST, port=PORT, reload=False)
