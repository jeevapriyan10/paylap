import threading
import time
from typing import Awaitable, Callable, Dict, Tuple, cast

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

"""
NOTE ON MULTI-INSTANCE CLUSTERING:
This token-bucket rate limiter maintains rate-limit buckets in-memory for single-instance
deployments. In multi-instance or clustered deployments, replace or back this store with
a distributed shared store such as Redis (e.g. redis-py with EVAL token-bucket Lua scripts)
to coordinate rate limits uniformly across application replicas.
"""


class TokenBucket:
    def __init__(self, capacity: int, refill_rate_per_sec: float):
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.refill_rate = refill_rate_per_sec
        self.last_update = time.time()
        self.lock = threading.Lock()

    def consume(self, tokens: float = 1.0) -> Tuple[bool, int, int]:
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            self.last_update = now

            # Refill tokens
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)

            if self.tokens >= tokens:
                self.tokens -= tokens
                remaining = int(self.tokens)
                return True, remaining, 0
            else:
                deficit = tokens - self.tokens
                retry_after = int(deficit / self.refill_rate) + 1
                return False, int(self.tokens), retry_after


class RateLimiter:
    def __init__(self, key_capacity: int = 120, key_rate: float = 2.0, ip_capacity: int = 60, ip_rate: float = 1.0):
        self.key_capacity = key_capacity
        self.key_rate = key_rate
        self.ip_capacity = ip_capacity
        self.ip_rate = ip_rate

        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def get_bucket(self, identifier: str, is_key: bool) -> TokenBucket:
        with self._lock:
            if identifier not in self._buckets:
                capacity = self.key_capacity if is_key else self.ip_capacity
                rate = self.key_rate if is_key else self.ip_rate
                self._buckets[identifier] = TokenBucket(capacity=capacity, refill_rate_per_sec=rate)
            return self._buckets[identifier]


_global_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Exclude internal health and docs endpoints from rate limiting
        path = request.url.path
        if path in ("/healthz", "/readyz", "/docs", "/openapi.json", "/"):
            return cast(Response, await call_next(request))

        # Check API key first, else fall back to IP address
        auth_header = request.headers.get("Authorization")
        is_key = False
        identifier = ""

        if auth_header and auth_header.startswith("Bearer pl_"):
            # Rate limit by API Key prefix + lookup_id
            parts = auth_header[7:].split("_")
            if len(parts) >= 3:
                identifier = f"key_{parts[1]}_{parts[2]}"
                is_key = True

        if not identifier:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                identifier = f"ip_{forwarded.split(',')[0].strip()}"
            else:
                client_ip = request.client.host if request.client else "127.0.0.1"
                identifier = f"ip_{client_ip}"

        bucket = _global_limiter.get_bucket(identifier, is_key=is_key)
        allowed, remaining, retry_after = bucket.consume(1.0)
        capacity = _global_limiter.key_capacity if is_key else _global_limiter.ip_capacity

        if not allowed:
            request_id = getattr(request.state, "request_id", "req_unknown")
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "type": "rate_limit_error",
                        "code": "rate_limit_exceeded",
                        "message": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                        "request_id": request_id,
                        "details": None,
                    }
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(capacity),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = cast(Response, await call_next(request))
        response.headers["X-RateLimit-Limit"] = str(capacity)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
