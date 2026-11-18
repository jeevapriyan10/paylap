from typing import Awaitable, Callable, cast

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = cast(Response, await call_next(request))

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none';"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        if settings.PAYLAP_ENV == "production":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"

        return response
