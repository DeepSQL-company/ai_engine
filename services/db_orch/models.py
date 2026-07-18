from pydantic import BaseModel, ConfigDict, Field


class DbConnectionConfig(BaseModel):
    host: str = Field(description="Хост PostgreSQL")
    port: int = Field(default=5432, description="Порт PostgreSQL")
    database: str = Field(description="Имя базы данных")
    user: str = Field(description="Имя пользователя")
    password: str = Field(description="Пароль")
    schema_name: str | None = Field(default=None, alias="schema", description="Схема по умолчанию")

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "host": "host.docker.internal",
                "port": 5432,
                "database": "demo",
                "user": "user",
                "password": "user",
                "schema": "bookings",
            }
        },
    )


class InitResponse(BaseModel):
    status: str
    message: str
    database: str


class DatabasesResponse(BaseModel):
    databases: list[str]


class SchemasResponse(BaseModel):
    schemas: list[str]


class TablesResponse(BaseModel):
    tables: list[str]


class ColumnInfo(BaseModel):
    name: str
    data_type: str
    is_nullable: bool
    column_default: str | None = None


class ColumnsResponse(BaseModel):
    columns: list[ColumnInfo]


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, description="Read-only SQL-запрос PostgreSQL")
    params: dict | list | None = Field(default=None, description="Параметры запроса")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sql": "SELECT status, COUNT(*) AS cnt FROM bookings.flights GROUP BY status",
            }
        }
    )


class QueryResponse(BaseModel):
    ok: bool = True
    columns: list[str]
    rows: list[dict]
    row_count: int
    total_row_count: int | None = None
    truncated: bool = False
    note: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    db_initialized: bool
