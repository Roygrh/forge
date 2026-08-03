"""The platform's error shape, wired once.

``openapi.yaml`` specifies every failure as ``{code, message, details}``. FastAPI's
default is ``{"detail": ...}``, so raising :class:`ApiError` and rendering it here is
what keeps the served responses and the published contract identical.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.schemas import ErrorResponse


class ApiError(Exception):
    """An error with a stable machine-readable code."""

    def __init__(
        self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def install_error_handlers(app: FastAPI) -> None:
    """Render :class:`ApiError` as the contract's error body."""

    @app.exception_handler(ApiError)
    async def _handle(request: Request, exc: ApiError) -> JSONResponse:
        body = ErrorResponse(code=exc.code, message=exc.message, details=exc.details)
        return JSONResponse(status_code=exc.status_code, content=body.model_dump(exclude_none=True))
