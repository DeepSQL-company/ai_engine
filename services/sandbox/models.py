from pydantic import BaseModel, ConfigDict, Field


class RunPythonRequest(BaseModel):
    code: str = Field(min_length=1, description="Python-код для выполнения в stateful worker")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": "import pandas as pd\nprint(pd.read_csv('data.csv').head())",
            }
        }
    )


class SaveSqlRequest(BaseModel):
    sql: str = Field(min_length=1, description="Read-only SQL-запрос PostgreSQL")
    filename: str = Field(min_length=1, description="Имя файла, например flights.csv")
    format: str = Field(pattern="^(?i)(csv|json)$", description="Формат файла: csv или json")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sql": "SELECT status, COUNT(*) AS cnt FROM bookings.flights GROUP BY status",
                "filename": "flights_by_status.csv",
                "format": "csv",
            }
        }
    )


class SandboxFileInfo(BaseModel):
    name: str
    size_bytes: int


class CreateSessionResponse(BaseModel):
    ok: bool = True
    message: str
    session_id: str
    files: list[str]


class RunPythonResponse(BaseModel):
    ok: bool
    stdout: str = ""
    stderr: str = ""
    files: list[str] = Field(default_factory=list)


class ListFilesResponse(BaseModel):
    ok: bool = True
    active: bool
    session_id: str
    files: list[SandboxFileInfo]
    max_files: int
    max_file_bytes: int


class SaveSqlResponse(BaseModel):
    ok: bool = True
    message: str
    filename: str
    format: str
    size_bytes: int
    row_count: int
    total_row_count: int | None = None
    truncated: bool = False
    note: str | None = None
    files: list[str]


class HealthResponse(BaseModel):
    status: str
    service: str
