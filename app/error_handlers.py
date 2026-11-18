import logging
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("paylap.errors")


def create_error_response(
    status_code: int,
    error_type: str,
    code: str,
    message: str,
    request_id: str,
    details: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    payload = {
        "error": {
            "type": error_type,
            "code": code,
            "message": message,
            "request_id": request_id,
            "details": details,
        }
    }
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "req_unknown")
        error_type = "client_error" if exc.status_code < 500 else "server_error"
        code = f"http_{exc.status_code}"
        
        # Friendly codes
        if exc.status_code == 401:
            code = "unauthorized"
            error_type = "authentication_error"
        elif exc.status_code == 403:
            code = "forbidden"
            error_type = "authorization_error"
        elif exc.status_code == 404:
            code = "not_found"
            error_type = "not_found_error"
        elif exc.status_code == 422:
            code = "validation_error"
            error_type = "invalid_request_error"
        elif exc.status_code == 429:
            code = "rate_limit_exceeded"
            error_type = "rate_limit_error"

        return create_error_response(
            status_code=exc.status_code,
            error_type=error_type,
            code=code,
            message=str(exc.detail),
            request_id=request_id,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "req_unknown")
        # Format validation errors cleanly without stack traces
        details = []
        for err in exc.errors():
            loc = " -> ".join(str(l) for l in err.get("loc", []))
            details.append({"location": loc, "message": err.get("msg")})

        return create_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_type="invalid_request_error",
            code="validation_failed",
            message="Request body or parameter validation failed",
            request_id=request_id,
            details=details,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "req_unknown")
        logger.error(
            f"Unhandled server exception on {request.method} {request.url.path}: {exc}",
            exc_info=True,
            extra={"request_id": request_id},
        )
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_type="api_error",
            code="internal_server_error",
            message="An unexpected internal server error occurred. Please contact support with the request_id.",
            request_id=request_id,
            details=None,
        )
