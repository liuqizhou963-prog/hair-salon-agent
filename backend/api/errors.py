"""Unified API error response helpers."""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _response(status_code: int, code: str, message: str, request: Request, details=None):
    body = {"code": code, "message": message, "request_id": _request_id(request)}
    if details is not None:
        body["details"] = jsonable_encoder(details)
    return JSONResponse(status_code=status_code, content=body)


async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
    details = None if isinstance(exc.detail, str) else exc.detail
    return _response(exc.status_code, f"HTTP_{exc.status_code}", detail, request, details)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return _response(422, "VALIDATION_ERROR", "请求参数校验失败", request, exc.errors())


async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled API error request_id={}", _request_id(request))
    return _response(500, "INTERNAL_ERROR", "服务器内部错误，请稍后重试", request)