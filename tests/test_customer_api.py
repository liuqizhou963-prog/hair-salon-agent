from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)
PASSWORD = "StrongPass123!"


def _register(phone: str):
    registered = client.post(
        "/api/auth/register",
        json={"phone": phone, "name": "原始姓名", "password": PASSWORD},
    )
    assert registered.status_code == 201, registered.text
    logged_in = client.post(
        "/api/auth/login",
        json={"phone": phone, "password": PASSWORD},
    )
    assert logged_in.status_code == 200, logged_in.text
    return {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


def test_customer_can_update_profile_through_authenticated_api():
    headers = _register("13940000001")

    response = client.patch(
        "/api/profile",
        headers=headers,
        json={"name": "更新后的姓名", "birthday": "08-18"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "user_id": response.json()["user_id"],
        "name": "更新后的姓名",
        "phone": "13940000001",
        "role": "customer",
        "birthday": "08-18",
    }


def test_profile_rejects_invalid_birthday_format():
    headers = _register("13940000002")

    response = client.patch(
        "/api/profile",
        headers=headers,
        json={"birthday": "0818"},
    )

    assert response.status_code == 422
