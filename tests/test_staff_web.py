from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_staff_web_page_is_available():
    response = client.get("/staff")

    assert response.status_code == 200
    assert "员工运营工作台" in response.text
