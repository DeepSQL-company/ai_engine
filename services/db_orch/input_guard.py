import re

PG_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
MAX_IDENTIFIER_LENGTH = 63
MAX_DATABASE_NAME_LENGTH = 128
MAX_HOST_LENGTH = 255

HOST_PATTERN = re.compile(r"^[a-zA-Z0-9._:-]+$")


class InputValidationError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def validate_pg_identifier(value: str, field: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_IDENTIFIER_LENGTH
        or not PG_IDENTIFIER_PATTERN.match(normalized)
    ):
        raise InputValidationError(f"{field}: недопустимый идентификатор PostgreSQL")
    return normalized


def validate_database_name(value: str, field: str = "database") -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_DATABASE_NAME_LENGTH
        or not PG_IDENTIFIER_PATTERN.match(normalized)
    ):
        raise InputValidationError(f"{field}: недопустимое имя базы данных")
    return normalized


def validate_host(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_HOST_LENGTH or not HOST_PATTERN.match(normalized):
        raise InputValidationError("host: недопустимый хост")
    return normalized


def validate_port(value: int) -> int:
    if value < 1 or value > 65535:
        raise InputValidationError("port: допустимы значения 1-65535")
    return value
