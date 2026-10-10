from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    if exc.status_code in {401, 403} and exc.code not in {"INVALID_CREDENTIALS", "LOGIN_RATE_LIMITED"}:
        try:
            from .audit import record_system_audit
            actor = getattr(request.state, "current_user", None)
            await record_system_audit(
                action="auth.permission_denied" if exc.status_code == 403 else "auth.session_invalid",
                request_id=getattr(request.state, "request_id", "unknown"),
                object_name=request.url.path,
                actor=actor,
                changes={"error_code": exc.code, "method": request.method},
            )
        except Exception:
            pass
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": getattr(request.state, "request_id", "unknown"),
                "details": exc.details,
            }
        },
    )
