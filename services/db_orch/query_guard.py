import json
import re
from typing import Any

import psycopg

from services.db_orch.config import MAX_QUERY_RESULT_CHARS, READONLY_QUERIES

COMMENT_BLOCK_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
FIRST_KEYWORD_PATTERN = re.compile(r"([a-z_]+)", re.IGNORECASE)

DANGEROUS_SQL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bCOPY\s+.*\bFROM\b", re.IGNORECASE | re.DOTALL), "COPY FROM запрещён"),
    (re.compile(r"\bINTO\s+(TEMP|TEMPORARY|UNLOGGED|TABLE)\b", re.IGNORECASE), "SELECT INTO запрещён"),
    (re.compile(r"\bpg_sleep\s*\(", re.IGNORECASE), "pg_sleep запрещён"),
    (re.compile(r"\bpg_read_file\s*\(", re.IGNORECASE), "pg_read_file запрещён"),
    (re.compile(r"\bpg_write_file\s*\(", re.IGNORECASE), "pg_write_file запрещён"),
    (re.compile(r"\blo_import\s*\(", re.IGNORECASE), "lo_import запрещён"),
    (re.compile(r"\bdblink(_exec)?\s*\(", re.IGNORECASE), "dblink запрещён"),
    (re.compile(r"\bEXECUTE\s+", re.IGNORECASE), "EXECUTE запрещён"),
    (re.compile(r";\s*\S", re.IGNORECASE), "Несколько SQL-команд через ';' запрещены"),
]

MAX_QUERY_PARAMS_JSON_CHARS = 10_000

WRITE_FIRST_KEYWORDS = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "MERGE",
        "TRUNCATE",
        "DROP",
        "CREATE",
        "ALTER",
        "GRANT",
        "REVOKE",
        "CALL",
        "DO",
        "VACUUM",
        "REINDEX",
        "CLUSTER",
        "COMMENT",
        "LOCK",
        "DISCARD",
        "LISTEN",
        "UNLISTEN",
        "NOTIFY",
        "LOAD",
        "REFRESH",
        "CHECKPOINT",
        "IMPORT",
        "MOVE",
        "RESET",
        "ABORT",
        "COMMIT",
        "ROLLBACK",
        "SAVEPOINT",
        "RELEASE",
        "START",
        "BEGIN",
    }
)


class QueryValidationError(Exception):
    def __init__(self, message: str, sql: str) -> None:
        self.message = message
        self.sql = sql
        super().__init__(message)


def strip_sql_comments(sql: str) -> str:
    without_blocks = COMMENT_BLOCK_PATTERN.sub(" ", sql)
    lines: list[str] = []
    for line in without_blocks.splitlines():
        in_quote = False
        quote_char = ""
        cut_at = len(line)
        index = 0
        while index < len(line) - 1:
            char = line[index]
            if char in {"'", '"'} and (index == 0 or line[index - 1] != "\\"):
                if not in_quote:
                    in_quote = True
                    quote_char = char
                elif quote_char == char:
                    in_quote = False
                    quote_char = ""
            if not in_quote and line[index : index + 2] == "--":
                cut_at = index
                break
            index += 1
        lines.append(line[:cut_at])
    return "\n".join(lines)


def extract_first_keyword(sql: str) -> str:
    cleaned = strip_sql_comments(sql).strip()
    while cleaned.startswith("("):
        cleaned = cleaned[1:].lstrip()
    match = FIRST_KEYWORD_PATTERN.search(cleaned)
    return match.group(1).upper() if match else ""


def validate_query_params(params: dict | list | None, sql: str) -> None:
    if params is None:
        return

    try:
        serialized = json.dumps(params, ensure_ascii=False, default=str)
    except TypeError as error:
        raise QueryValidationError("params должны быть JSON-сериализуемыми.", sql) from error

    if len(serialized) > MAX_QUERY_PARAMS_JSON_CHARS:
        raise QueryValidationError(
            f"params слишком большие (>{MAX_QUERY_PARAMS_JSON_CHARS} символов).",
            sql,
        )

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise QueryValidationError("Ключи params должны быть строками.", sql)
                _walk(item)
            return
        if isinstance(value, list):
            for item in value:
                _walk(item)
            return
        if value is None or isinstance(value, (bool, int, float, str)):
            return
        raise QueryValidationError(
            "params могут содержать только строки, числа, bool, null, list и dict.",
            sql,
        )

    _walk(params)


def validate_dangerous_sql_patterns(sql: str) -> None:
    cleaned = strip_sql_comments(sql)
    for pattern, message in DANGEROUS_SQL_PATTERNS:
        if pattern.search(cleaned):
            raise QueryValidationError(message, sql)


def validate_readonly_sql(sql: str) -> None:
    if not READONLY_QUERIES:
        return

    normalized = sql.strip()
    if not normalized:
        raise QueryValidationError("SQL-запрос пустой.", sql)

    validate_dangerous_sql_patterns(normalized)

    if normalized.endswith(";"):
        normalized = normalized[:-1].strip()

    if ";" in normalized:
        raise QueryValidationError(
            "Разрешён только один SQL-запрос за вызов. Убери несколько команд через ';'.",
            sql,
        )

    first_keyword = extract_first_keyword(normalized)
    if not first_keyword:
        raise QueryValidationError("Не удалось распознать SQL-запрос.", sql)

    if first_keyword in WRITE_FIRST_KEYWORDS:
        raise QueryValidationError(
            f"Команда {first_keyword} запрещена: разрешены только read-only запросы.",
            sql,
        )


def format_agent_error(
    *,
    error_type: str,
    message: str,
    sql: str,
    hint: str | None = None,
    pg_error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "error_type": error_type,
        "message": message,
        "sql": sql,
    }
    if hint:
        payload["hint"] = hint
    if pg_error:
        payload["pg_error"] = pg_error
    return payload


def format_validation_error(error: QueryValidationError) -> dict[str, Any]:
    return format_agent_error(
        error_type="read_only_violation",
        message=error.message,
        sql=error.sql,
        hint=(
            "Используй read-only SQL: SELECT, WITH, EXPLAIN, SHOW, TABLE, VALUES, COPY TO и т.п. "
            "Без INSERT/UPDATE/DELETE/DDL."
        ),
    )


def format_sql_error(error: Exception, sql: str) -> dict[str, Any]:
    pg_error = str(error)
    first_line = pg_error.splitlines()[0] if pg_error else "Неизвестная ошибка PostgreSQL"

    if isinstance(error, psycopg.errors.ReadOnlySqlTransaction):
        return format_agent_error(
            error_type="read_only_violation",
            message=f"Запрос отклонён read-only транзакцией PostgreSQL: {first_line}",
            sql=sql,
            hint=(
                "Запрос пытается изменить данные или выполнить запрещённую операцию. "
                "Используй read-only SQL для чтения."
            ),
            pg_error=pg_error,
        )

    hint = "Проверь имена таблиц и колонок по метаданным, синтаксис PostgreSQL и read-only ограничения."
    if "does not exist" in pg_error:
        hint = "Похоже, указаны неверные имена таблиц или колонок. Сверься с метаданными БД."

    return format_agent_error(
        error_type="sql_error",
        message=f"SQL-запрос завершился ошибкой: {first_line}",
        sql=sql,
        hint=hint,
        pg_error=pg_error,
    )


def build_limited_result(
    columns: list[str],
    rows: list[dict[str, Any]],
    max_chars: int = MAX_QUERY_RESULT_CHARS,
) -> dict[str, Any]:
    total_row_count = len(rows)
    included_rows: list[dict[str, Any]] = []

    for row in rows:
        candidate_rows = included_rows + [row]
        payload = {
            "ok": True,
            "columns": columns,
            "rows": candidate_rows,
            "row_count": len(candidate_rows),
            "total_row_count": total_row_count,
        }
        if len(json.dumps(payload, ensure_ascii=False, default=str)) > max_chars:
            break
        included_rows = candidate_rows

    truncated = len(included_rows) < total_row_count
    result: dict[str, Any] = {
        "ok": True,
        "columns": columns,
        "rows": included_rows,
        "row_count": len(included_rows),
        "total_row_count": total_row_count,
    }

    if truncated:
        result["truncated"] = True
        result["note"] = (
            f"Результат обрезан до ~{max_chars} символов. "
            f"Показано {len(included_rows)} из {total_row_count} строк. "
            "Сузь SELECT: LIMIT, фильтры или агрегация."
        )

    return result
