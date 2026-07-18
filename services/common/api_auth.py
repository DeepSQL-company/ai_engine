import secrets
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


def _extract_api_key(request: Request) -> str | None:
    header_key = request.headers.get("X-API-Key")
    if header_key:
        return header_key.strip()

    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()

    return None


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        api_key: str,
        public_paths: frozenset[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._api_key = api_key
        self._public_paths = public_paths or frozenset({"/health"})

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self._public_paths:
            return await call_next(request)

        if not self._api_key:
            return JSONResponse(
                status_code=503,
                content={"detail": "API_KEY не задан на сервере"},
            )

        provided = _extract_api_key(request)
        if not provided or not secrets.compare_digest(provided, self._api_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "Неверный или отсутствующий API key"},
            )

        return await call_next(request)


def api_key_headers(api_key: str) -> dict[str, str]:
    if not api_key:
        return {}
    return {"X-API-Key": api_key}


def install_api_key_middleware(
    app: FastAPI,
    api_key: str,
    public_paths: frozenset[str] | None = None,
) -> None:
    if not api_key:
        return
    app.add_middleware(ApiKeyMiddleware, api_key=api_key, public_paths=public_paths)


def apply_openapi_api_key(app) -> None:
    from fastapi.openapi.utils import get_openapi

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        components.setdefault("securitySchemes", {}).update(openapi_security_scheme())
        schema["security"] = [{"ApiKeyAuth": []}]
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi


def openapi_security_scheme() -> dict:
    return {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        }
    }

