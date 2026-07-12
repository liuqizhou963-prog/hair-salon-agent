from fastapi.testclient import TestClient

from backend.main import app
from backend.middleware import InMemoryRateLimiter


client = TestClient(app)


def test_rate_limiter_rejects_the_next_request_in_a_window():
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)

    assert limiter.allow("client", now=100)[0] is True
    assert limiter.allow("client", now=101)[0] is True
    allowed, retry_after = limiter.allow("client", now=102)

    assert allowed is False
    assert retry_after > 0
    assert limiter.allow("other-client", now=102)[0] is True


def test_validation_errors_use_the_unified_response_shape():
    response = client.post("/api/auth/login", json={"phone": "13900000000"})

    assert response.status_code == 422
    assert response.headers["X-Request-ID"]
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["message"] == "请求参数校验失败"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert response.json()["details"]


def test_http_errors_echo_the_request_id():
    response = client.get(
        "/api/route-that-does-not-exist",
        headers={"X-Request-ID": "interview-request-001"},
    )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "interview-request-001"
    assert response.json() == {
        "code": "HTTP_404",
        "message": "Not Found",
        "request_id": "interview-request-001",
    }