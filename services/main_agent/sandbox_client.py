from typing import Any

import httpx

from services.main_agent.config import SANDBOX_TIMEOUT_SEC, SANDBOX_URL


class SandboxServiceError(Exception):
    def __init__(self, payload: dict[str, Any] | str) -> None:
        if isinstance(payload, dict):
            self.payload = payload
            message = payload.get("message", "Ошибка sandbox")
        else:
            self.payload = {"ok": False, "error_type": "unknown", "message": payload}
            message = payload
        super().__init__(message)


def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    url = f"{SANDBOX_URL.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=SANDBOX_TIMEOUT_SEC) as client:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as error:
        detail: dict[str, Any] | str = error.response.text
        try:
            parsed = error.response.json().get("detail", detail)
            if isinstance(parsed, dict):
                raise SandboxServiceError(parsed) from error
            detail = parsed
        except SandboxServiceError:
            raise
        except Exception:
            pass
        raise SandboxServiceError(str(detail)) from error
    except Exception as error:
        raise SandboxServiceError(str(error)) from error


def create_sandbox(session_id: str) -> dict[str, Any]:
    return _request("POST", f"/sessions/{session_id}/create")


def run_python(session_id: str, code: str) -> dict[str, Any]:
    return _request("POST", f"/sessions/{session_id}/run", json={"code": code})


def list_sandbox_files(session_id: str) -> dict[str, Any]:
    return _request("GET", f"/sessions/{session_id}/files")


def save_sql_to_sandbox(
    session_id: str,
    sql: str,
    filename: str,
    file_format: str,
) -> dict[str, Any]:
    return _request(
        "POST",
        f"/sessions/{session_id}/save_sql",
        json={"sql": sql, "filename": filename, "format": file_format},
    )
