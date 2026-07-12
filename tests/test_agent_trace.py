from backend.agents.retention_graph import run_retention_graph
from backend.agents.staff_graph import run_staff_query


def _nodes(result):
    return [step["node"] for step in result["trace"]["steps"]]


def test_staff_agent_trace_contains_route_tool_and_response_nodes():
    result = run_staff_query("你好", "trace-requester")

    assert result["trace_id"] == result["trace"]["trace_id"]
    assert _nodes(result) == ["classify_request", "query_help", "format_response"]


def test_retention_agent_trace_contains_all_workflow_nodes():
    result = run_retention_graph("trace-requester")

    assert result["trace_id"] == result["trace"]["trace_id"]
    assert _nodes(result) == [
        "collect_candidates",
        "classify_candidates",
        "generate_recommendations",
    ]