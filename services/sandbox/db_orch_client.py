from typing import Any

import httpx

from services.sandbox.config import DB_ORCH_EXPORT_TIMEOUT_SEC, DB_ORCH_URL


class DbOrchError(Exception):
    def __init__(self, payload: dict[str, Any] | str) -> None:
        if isinstance(payload, dict):
            self.payload = payload
            message = payload.get("message", "Ошибка db_orch")
        else:
            self.payload = {"ok": False, "error_type": "unknown", "message": payload}
            message = payload
        super().__init__(message)


def execute_sql_export(sql: str, params: dict | list | None = None) -> dict[str, Any]:
    url = f"{DB_ORCH_URL.rstrip('/')}/query/export"
    payload: dict[str, Any] = {"sql": sql}
    if params is not None:
        payload["params"] = params

    try:
        with httpx.Client(timeout=DB_ORCH_EXPORT_TIMEOUT_SEC) as client:
            response = client.post(url, json=payload)
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
