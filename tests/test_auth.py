from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def _register(phone: str, name: str = "认证客户"):
    response = client.post(
        "/api/auth/register",
        json={"phone": phone, "name": name, "password": "StrongPass123!"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login(phone: str):
    response = client.post(
        "/api/auth/login",
        json={"phone": phone, "password": "StrongPass123!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth_headers(phone: str):
    return {"Authorization": f"Bearer {_login(phone)}"}


def _first_slot():
    stylist = client.get("/api/stylists", params={"specialty": "护理"}).json()[0]
    slot = client.get(f"/api/stylists/{stylist['stylist_id']}/slots").json()[0]
    return stylist, slot


def test_customer_can_register_login_and_read_current_user():
    phone = "13920000001"
    _register(phone, "认证客户")

    me = client.get("/api/auth/me", headers=_auth_headers(phone))

    assert me.status_code == 200
    assert me.json()["phone"] == phone
    assert me.json()["role"] == "customer"


def test_duplicate_registration_and_wrong_password_are_rejected():
    phone = "13920000004"
    _register(phone)

    duplicate = client.post(
        "/api/auth/register",
        json={"phone": phone, "name": "重复客户", "password": "StrongPass123!"},
    )
    wrong_password = client.post(
        "/api/auth/login",
        json={"phone": phone, "password": "WrongPass123!"},
    )

    assert duplicate.status_code == 409
    assert wrong_password.status_code == 401


def test_customer_cannot_read_staff_customer_list():
    _register("13920000005")
    headers = _auth_headers("13920000005")

    response = client.get("/api/customers", headers=headers)

    assert response.status_code == 403


def test_appointment_creation_requires_login():
    stylist, slot = _first_slot()

    response = client.post(
        "/api/appointments",
        json={
            "stylist_id": stylist["stylist_id"],
            "slot_id": slot["slot_id"],
            "service": "护理",
        },
    )

    assert response.status_code == 401


def test_customer_can_only_cancel_own_appointment():
    owner_phone = "13920000002"
    other_phone = "13920000003"
    _register(owner_phone, "预约本人")
    _register(other_phone, "其他客户")
    stylist, slot = _first_slot()

    booking = client.post(
        "/api/appointments",
        headers=_auth_headers(owner_phone),
        json={
            "stylist_id": stylist["stylist_id"],
            "slot_id": slot["slot_id"],
            "service": "护理",
        },
    )
    assert booking.status_code == 200, booking.text
    appointment_id = booking.json()["appointment_id"]

    denied = client.delete(
        f"/api/appointments/{appointment_id}",
        headers=_auth_headers(other_phone),
    )

    assert denied.status_code == 404
