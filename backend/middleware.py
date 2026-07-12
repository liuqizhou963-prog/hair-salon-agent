"""Request IDs and process-local API rate limiting middleware."""

from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.config import settings


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID")
        if not request_id or len(request_id) > 100:
            request_id = str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class InMemoryRateLimiter:
    """A small single-process limiter for demos and one-worker deployments."""

    def __init__(self, max_requests: int, window_seconds: int):
        if max_requests <= 0 or window_seconds <= 0:
            raise ValueError("Rate limit values must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        current = monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.max_requests:
                retry_after = max(1, int(events[0] + self.window_seconds - current))
                return False, retry_after
            events.append(current)
            return True, 0


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, enabled: bool | None = None, max_requests: int | None = None, window_seconds: int | None = None):
        super().__init__(app)
        self.enabled = settings.RATE_LIMIT_ENABLED if enabled is None else enabled
        self.limiter = InMemoryRateLimiter(
            max_requests or settings.RATE_LIMIT_REQUESTS,
            window_seconds or settings.RATE_LIMIT_WINDOW_SECONDS,
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled or not request.url.path.startswith("/api"):
            return await call_next(request)
        client_host = request.client.host if request.client else "unknown"
        allowed, retry_after = self.limiter.allow(client_host)
        if not allowed:
            request_id = getattr(request.state, "request_id", str(uuid4()))
            return JSONResponse(
                status_code=429,
                content={
                    "code": "RATE_LIMITED",
                    "message": "请求过于频繁，请稍后再试",
                    "request_id": request_id,
                },
                headers={"Retry-After": str(retry_after), "X-Request-ID": request_id},
            )
        return await call_next(request)