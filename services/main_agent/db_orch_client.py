from typing import Any

import httpx

from services.main_agent.config import DB_ORCH_TIMEOUT_SEC, DB_ORCH_URL


class DbOrchError(Exception):
    def __init__(self, payload: dict[str, Any] | str) -> None:
        if isinstance(payload, dict):
            self.payload = payload
            message = payload.get("message", "Ошибка db_orch")
        else:
            self.payload = {
                "ok": False,
                "error_type": "unknown",
                "message": payload,
            }
            message = payload
        super().__init__(message)


def _request(method: str, path: str, **kwargs: Any) -> Any:
    url = f"{DB_ORCH_URL.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=DB_ORCH_TIMEOUT_SEC) as client:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as error:
        detail: dict[str, Any] | str = error.response.text
        try:
            parsed = error.response.json().get("detail", detail)
            if isinstance(parsed, dict):
                raise DbOrchError(parsed) from error
            detail = parsed
        except DbOrchError:
            raise
        except Exception:
            pass
        raise DbOrchError(str(detail)) from error
    except Exception as error:
        raise DbOrchError(str(error)) from error


def fetch_metadata_text() -> str:
    databases = _request("GET", "/databases")["databases"]
    schemas = _request("GET", "/schemas")["schemas"]

    lines: list[str] = []
    lines.append(f"Databases: {', '.join(databases)}")
    lines.append("")

    for schema in schemas:
        lines.append(f"Schema: {schema}")
        tables = _request("GET", "/tables", params={"schema": schema})["tables"]
        for table in tables:
            lines.append(f"  Table: {table}")
            columns = _request("GET", "/columns", params={"schema": schema, "table": table})["columns"]
            for column in columns:
                nullable = "NULL" if column["is_nullable"] else "NOT NULL"
                default = f" DEFAULT {column['column_default']}" if column.get("column_default") else ""
                lines.append(f"    - {column['name']}: {column['data_type']} {nullable}{default}")
        lines.append("")

    return "\n".join(lines).strip()


def execute_sql(sql: str, params: dict | list | None = None) -> dict[str, Any]:
    payload = {"sql": sql}
    if params is not None:
        payload["params"] = params
    return _request("POST", "/query", json=payload)


def execute_sql_export(sql: str, params: dict | list | None = None) -> dict[str, Any]:
    payload = {"sql": sql}
    if params is not None:
        payload["params"] = params
    return _request("POST", "/query/export", json=payload)
