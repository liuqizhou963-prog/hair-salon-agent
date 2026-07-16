"""Replaceable outbound channel for retention messages.

The first version uses MockMessageSender. A real WeChat implementation can satisfy
the same interface without changing task rules or contact history handling.
"""

from __future__ import annotations

from dataclasses import dataclass
import uuid


@dataclass(frozen=True)
class SendResult:
    success: bool
    provider_message_id: str | None = None
    failure_reason: str | None = None


class RetentionMessageSender:
    channel = "unknown"

    def send(self, customer_id: str, message: str, *, simulate_failure: bool = False) -> SendResult:
        raise NotImplementedError


class MockMessageSender(RetentionMessageSender):
    channel = "mock"

    def send(self, customer_id: str, message: str, *, simulate_failure: bool = False) -> SendResult:
        if simulate_failure:
            return SendResult(success=False, failure_reason="模拟渠道发送失败")
        return SendResult(success=True, provider_message_id=f"mock-{uuid.uuid4().hex}")


class WeChatMessageSender(RetentionMessageSender):
    """Reserved adapter. Real credentials and platform templates are intentionally required."""
    channel = "wechat"

    def send(self, customer_id: str, message: str, *, simulate_failure: bool = False) -> SendResult:
        return SendResult(success=False, failure_reason="微信渠道尚未配置")
