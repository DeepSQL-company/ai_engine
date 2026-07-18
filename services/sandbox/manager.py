import csv
import json
import re
import select
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from services.sandbox.config import (
    SANDBOX_EXEC_TIMEOUT_SEC,
    SANDBOX_MAX_FILE_BYTES,
    SANDBOX_MAX_FILES,
    SANDBOX_ROOT,
)
from services.sandbox.db_orch_client import DbOrchError, execute_sql_export

SAFE_FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


class SandboxError(Exception):
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        super().__init__(payload.get("message", "Ошибка песочницы"))


def _error(error_type: str, message: str, **extra: Any) -> SandboxError:
    payload = {"ok": False, "error_type": error_type, "message": message}
    payload.update(extra)
    return SandboxError(payload)


def _validate_filename(filename: str) -> str:
    name = filename.strip()
    if not name or not SAFE_FILENAME_PATTERN.match(name):
        raise _error(
            "invalid_filename",
            "Имя файла должно содержать только буквы, цифры, '_', '-', '.' и не быть пустым.",
        )
    if name.startswith("."):
        raise _error("invalid_filename", "Скрытые файлы запрещены.")
    return name


class SandboxSession:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.workspace = SANDBOX_ROOT / session_id
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self.active = False

    def _list_data_files(self) -> list[Path]:
        if not self.workspace.exists():
            return []
        return sorted(
            path
            for path in self.workspace.iterdir()
            if path.is_file() and not path.name.startswith(".")
        )

    def _start_worker(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._process = subprocess.Popen(
            [sys.executable, "-m", "services.sandbox.worker"],
            cwd=str(self.workspace),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.active = True

    def _stop_worker(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        self.active = False

    def create(self) -> dict[str, Any]:
        with self._lock:
            self._stop_worker()
            if self.workspace.exists():
                shutil.rmtree(self.workspace)
            self._start_worker()
            return {
                "ok": True,
                "message": "Новая песочница создана. Предыдущее состояние удалено.",
                "session_id": self.session_id,
                "files": [],
            }

    def _require_active(self) -> None:
        if not self.active or self._process is None or self._process.poll() is not None:
            raise _error(
                "sandbox_not_ready",
                "Песочница не создана или worker остановлен. Сначала вызови create_sandbox.",
            )

    def run_python(self, code: str) -> dict[str, Any]:
        with self._lock:
            self._require_active()
            assert self._process is not None and self._process.stdin is not None

            payload = json.dumps({"code": code}, ensure_ascii=False)
            self._process.stdin.write(payload + "\n")
            self._process.stdin.flush()

            stdout = self._process.stdout
            if stdout is None:
                raise _error("sandbox_exec_failed", "Worker stdout недоступен.")

            ready, _, _ = select.select([stdout], [], [], SANDBOX_EXEC_TIMEOUT_SEC)
            if not ready:
                self._stop_worker()
                raise _error(
                    "sandbox_timeout",
                    f"Python-код выполнялся дольше {SANDBOX_EXEC_TIMEOUT_SEC} секунд. Песочница сброшена.",
                )

            response_line = stdout.readline()
            if not response_line:
                raise _error("sandbox_exec_failed", "Worker песочницы не ответил.")

            result = json.loads(response_line)
            result["files"] = [path.name for path in self._list_data_files()]
            return result

    def list_files(self) -> dict[str, Any]:
        with self._lock:
            files = [
                {"name": path.name, "size_bytes": path.stat().st_size}
                for path in self._list_data_files()
            ]
            return {
                "ok": True,
                "active": self.active,
                "session_id": self.session_id,
                "files": files,
                "max_files": SANDBOX_MAX_FILES,
                "max_file_bytes": SANDBOX_MAX_FILE_BYTES,
            }

    def save_sql_to_file(self, sql: str, filename: str, file_format: str) -> dict[str, Any]:
        with self._lock:
            self._require_active()
            safe_name = _validate_filename(filename)
            normalized_format = file_format.lower().strip()
            if normalized_format not in {"json", "csv"}:
                raise _error("invalid_format", "Поддерживаются форматы: json, csv.")

            extension = f".{normalized_format}"
            if not safe_name.endswith(extension):
                safe_name = f"{safe_name}{extension}"

            target = self.workspace / safe_name
            existing_files = self._list_data_files()
            if target not in existing_files and len(existing_files) >= SANDBOX_MAX_FILES:
                raise _error(
                    "file_limit",
                    f"В песочнице уже {SANDBOX_MAX_FILES} файлов. Удали или перезапиши существующий.",
                )

            try:
                query_result = execute_sql_export(sql)
            except DbOrchError as error:
                raise _error(
                    "sql_export_failed",
                    error.payload.get("message", str(error)),
                    details=error.payload,
                ) from error

            columns = query_result.get("columns", [])
            rows = query_result.get("rows", [])

            if normalized_format == "json":
                content = json.dumps(
                    {
                        "columns": columns,
                        "rows": rows,
                        "row_count": query_result.get("row_count", len(rows)),
                        "total_row_count": query_result.get("total_row_count", len(rows)),
                        "truncated": query_result.get("truncated", False),
                    },
                    ensure_ascii=False,
                    default=str,
                )
                target.write_text(content, encoding="utf-8")
            else:
                with target.open("w", encoding="utf-8", newline="") as file:
                    writer = csv.DictWriter(file, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(rows)

            size_bytes = target.stat().st_size
            if size_bytes > SANDBOX_MAX_FILE_BYTES:
                target.unlink(missing_ok=True)
                raise _error(
                    "file_too_large",
                    f"Файл {safe_name} превышает лимит {SANDBOX_MAX_FILE_BYTES} байт.",
                )

            return {
                "ok": True,
                "message": f"SQL-результат сохранён в {safe_name}",
                "filename": safe_name,
                "format": normalized_format,
                "size_bytes": size_bytes,
                "row_count": query_result.get("row_count", len(rows)),
                "total_row_count": query_result.get("total_row_count", len(rows)),
                "truncated": query_result.get("truncated", False),
                "note": query_result.get("note"),
                "files": [path.name for path in self._list_data_files()],
            }


class SandboxManager:
    def __init__(self) -> None:
        self._sessions: dict[str, SandboxSession] = {}
        self._lock = threading.Lock()

    def get_session(self, session_id: str) -> SandboxSession:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SandboxSession(session_id)
            return self._sessions[session_id]


sandbox_manager = SandboxManager()
