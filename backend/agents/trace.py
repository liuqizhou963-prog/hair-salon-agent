"""Small structured trace helper shared by Agent workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from loguru import logger


def new_trace(workflow: str) -> dict[str, Any]:
    trace_id = str(uuid4())
    return {
        "trace_id": trace_id,
        "trace": {"trace_id": trace_id, "workflow": workflow, "steps": []},
    }


def trace_node(
    state: dict[str, Any],
    node: str,
    *,
    status: str = "completed",
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace_id = state.get("trace_id") or str(uuid4())
    trace = dict(state.get("trace") or {})
    trace.setdefault("trace_id", trace_id)
    steps = list(trace.get("steps") or [])
    event: dict[str, Any] = {
        "node": node,
        "status": status,
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
    }
    if detail:
        event["detail"] = detail
    steps.append(event)
    trace["steps"] = steps
    logger.info(
        "agent_trace trace_id={} workflow={} node={} status={}",
        trace_id,
        trace.get("workflow", "unknown"),
        node,
        status,
    )
    return {**state, "trace_id": trace_id, "trace": trace}