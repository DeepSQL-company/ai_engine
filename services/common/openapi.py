from typing import Any

API_VERSION = "1.0.0"

# Swagger / ReDoc / OpenAPI schema — без API key (сами эндпоинты API ключ всё равно требуют).
DOCS_PUBLIC_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})


def swagger_kwargs(
    *,
    title: str,
    description: str,
    tags: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "version": API_VERSION,
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
        "openapi_tags": tags or [],
    }
