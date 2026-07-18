import logging

import uvicorn
from fastapi import FastAPI, HTTPException, Path

from services.common.openapi import swagger_kwargs
from services.sandbox.config import APP_TITLE, HOST, PORT
from services.sandbox.manager import SandboxError, sandbox_manager
from services.sandbox.models import (
    CreateSessionResponse,
    HealthResponse,
    ListFilesResponse,
    RunPythonRequest,
    RunPythonResponse,
    SaveSqlRequest,
    SaveSqlResponse,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    **swagger_kwargs(
        title=APP_TITLE,
        description=(
            "Stateful Python-песочница: worker на session_id, файлы на диске, "
            "run_python с numpy/pandas, save_sql через db_orch export."
        ),
        tags=[
            {"name": "health", "description": "Проверка состояния сервиса"},
            {"name": "sessions", "description": "Управление сессиями песочницы"},
        ],
    )
)


@app.get("/health", response_model=HealthResponse, tags=["health"], summary="Health check")
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=APP_TITLE)


@app.post(
    "/sessions/{session_id}/create",
    response_model=CreateSessionResponse,
    tags=["sessions"],
    summary="Создать песочницу",
    description="Создаёт новую stateful-сессию. Старое состояние и файлы удаляются.",
)
def create_session(
    session_id: str = Path(..., description="ID сессии, обычно chat_id агента"),
) -> CreateSessionResponse:
    try:
        return CreateSessionResponse(**sandbox_manager.get_session(session_id).create())
    except SandboxError as error:
        raise HTTPException(status_code=400, detail=error.payload) from error


@app.post(
    "/sessions/{session_id}/run",
    response_model=RunPythonResponse,
    tags=["sessions"],
    summary="Выполнить Python",
    description="Выполняет код в stateful worker. Файлы сессии доступны из cwd.",
)
def run_python(
    session_id: str = Path(..., description="ID сессии"),
    request: RunPythonRequest = ...,
) -> RunPythonResponse:
    try:
        return RunPythonResponse(**sandbox_manager.get_session(session_id).run_python(request.code))
    except SandboxError as error:
        raise HTTPException(status_code=400, detail=error.payload) from error


@app.get(
    "/sessions/{session_id}/files",
    response_model=ListFilesResponse,
    tags=["sessions"],
    summary="Список файлов сессии",
)
def list_files(
    session_id: str = Path(..., description="ID сессии"),
) -> ListFilesResponse:
    try:
        return ListFilesResponse(**sandbox_manager.get_session(session_id).list_files())
    except SandboxError as error:
        raise HTTPException(status_code=400, detail=error.payload) from error


@app.post(
    "/sessions/{session_id}/save_sql",
    response_model=SaveSqlResponse,
    tags=["sessions"],
    summary="Сохранить SQL-результат в файл",
    description="Выполняет read-only SQL через db_orch /query/export и сохраняет csv/json в песочницу.",
)
def save_sql(
    session_id: str = Path(..., description="ID сессии"),
    request: SaveSqlRequest = ...,
) -> SaveSqlResponse:
    try:
        result = sandbox_manager.get_session(session_id).save_sql_to_file(
            request.sql,
            request.filename,
            request.format,
        )
        return SaveSqlResponse(**result)
    except SandboxError as error:
        raise HTTPException(status_code=400, detail=error.payload) from error


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run("services.sandbox.main:app", host=HOST, port=PORT, reload=False)
