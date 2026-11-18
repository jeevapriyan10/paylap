from typing import Awaitable, Callable, cast

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# 5 MB maximum request body size limit
MAX_BODY_SIZE_BYTES = 5 * 1024 * 1024


class BodyLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > MAX_BODY_SIZE_BYTES:
                    request_id = getattr(request.state, "request_id", "req_unknown")
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "type": "invalid_request_error",
                                "code": "payload_too_large",
                                "message": f"Request body exceeds limit of {MAX_BODY_SIZE_BYTES} bytes",
                                "request_id": request_id,
                                "details": None,
                            }
                        },
                    )
            except ValueError:
                pass

        return cast(Response, await call_next(request))
