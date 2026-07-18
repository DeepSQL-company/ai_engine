from contextlib import contextmanager
import os
from typing import Any

import psycopg
import yaml
from psycopg.rows import dict_row

from services.db_orch.config import DEFAULT_CONFIG_PATH, READONLY_QUERIES
from services.db_orch.models import ColumnInfo, DbConnectionConfig
from services.db_orch.query_guard import (
    QueryValidationError,
    build_limited_result,
    format_sql_error,
    format_validation_error,
    validate_query_params,
    validate_readonly_sql,
)


class DbNotInitializedError(Exception):
    pass


class DbQueryError(Exception):
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        super().__init__(payload.get("message", "Ошибка SQL-запроса"))


class DbManager:
    def __init__(self) -> None:
        self._config: DbConnectionConfig | None = None

    @property
    def is_initialized(self) -> bool:
        return self._config is not None

    @property
    def config(self) -> DbConnectionConfig:
        if self._config is None:
            raise DbNotInitializedError("Сервис не инициализирован. Вызовите POST /init")
        return self._config

    def config_from_env(self) -> DbConnectionConfig | None:
        host = os.getenv("DB_HOST")
        if not host:
            return None

        return DbConnectionConfig(
            host=host,
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", os.getenv("DB_DATABASE", "postgres")),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            schema=os.getenv("DB_SCHEMA"),
        )

    def load_default_config(self) -> DbConnectionConfig:
        env_config = self.config_from_env()
        if env_config is not None:
            return env_config

        if not DEFAULT_CONFIG_PATH.exists():
            raise FileNotFoundError(
                f"Конфиг не найден: {DEFAULT_CONFIG_PATH}. "
                "Задайте DB_HOST/DB_NAME/DB_USER/DB_PASSWORD или db.local.yaml"
            )

        with DEFAULT_CONFIG_PATH.open(encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}

        return DbConnectionConfig(
            host=raw["host"],
            port=raw.get("port", 5432),
            database=raw["database"],
            user=raw["user"],
            password=raw["password"],
            schema=raw.get("schema"),
        )

    def init(self, config: DbConnectionConfig) -> None:
        with self._connect(config.database, config=config) as conn:
            conn.execute("SELECT 1")
        self._config = config

    def _connection_kwargs(
        self,
        database: str | None = None,
        config: DbConnectionConfig | None = None,
    ) -> dict[str, Any]:
        resolved = config or self.config
        return {
            "host": resolved.host,
            "port": resolved.port,
            "dbname": database or resolved.database,
            "user": resolved.user,
            "password": resolved.password,
        }

    @contextmanager
    def _connect(
        self,
        database: str | None = None,
        config: DbConnectionConfig | None = None,
    ):
        with psycopg.connect(**self._connection_kwargs(database, config)) as conn:
            yield conn

    @contextmanager
    def _dict_cursor(self, database: str | None = None):
        with psycopg.connect(**self._connection_kwargs(database), row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                yield cursor

    def list_databases(self) -> list[str]:
        with self._dict_cursor("postgres") as cursor:
            cursor.execute(
                """
                SELECT datname
                FROM pg_database
                WHERE datallowconn
                  AND datistemplate = false
                ORDER BY datname
                """
            )
            return [row["datname"] for row in cursor.fetchall()]

    def list_schemas(self, database: str | None = None) -> list[str]:
        with self._dict_cursor(database) as cursor:
            cursor.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
                  AND schema_name NOT LIKE 'pg_toast%%'
                  AND schema_name NOT LIKE 'pg_temp%%'
                ORDER BY schema_name
                """
            )
            return [row["schema_name"] for row in cursor.fetchall()]

    def list_tables(self, schema: str, database: str | None = None) -> list[str]:
        with self._dict_cursor(database) as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """,
                (schema,),
            )
            return [row["table_name"] for row in cursor.fetchall()]

    def list_columns(
        self,
        schema: str,
        table: str,
        database: str | None = None,
    ) -> list[ColumnInfo]:
        with self._dict_cursor(database) as cursor:
            cursor.execute(
                """
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                ORDER BY ordinal_position
                """,
                (schema, table),
            )
            return [
                ColumnInfo(
                    name=row["column_name"],
                    data_type=row["data_type"],
                    is_nullable=row["is_nullable"] == "YES",
                    column_default=row["column_default"],
                )
                for row in cursor.fetchall()
            ]

    def execute_query(
        self,
        sql: str,
        params: dict | list | None = None,
        max_result_chars: int | None = None,
    ) -> dict[str, Any]:
        from services.db_orch.config import MAX_QUERY_RESULT_CHARS

        validate_readonly_sql(sql)
        validate_query_params(params, sql)
        limit = max_result_chars if max_result_chars is not None else MAX_QUERY_RESULT_CHARS

        try:
            with psycopg.connect(**self._connection_kwargs(), row_factory=dict_row) as conn:
                with conn.transaction():
                    if READONLY_QUERIES:
                        conn.execute("SET TRANSACTION READ ONLY")
                    with conn.cursor() as cursor:
                        cursor.execute(sql, params or None)
                        if cursor.description is None:
                            return build_limited_result([], [], max_chars=limit)

                        columns = [desc.name for desc in cursor.description]
                        rows = cursor.fetchall()
                        return build_limited_result(columns, rows, max_chars=limit)
        except QueryValidationError as error:
            raise DbQueryError(format_validation_error(error)) from error
        except DbQueryError:
            raise
        except Exception as error:
            raise DbQueryError(format_sql_error(error, sql)) from error


db_manager = DbManager()
