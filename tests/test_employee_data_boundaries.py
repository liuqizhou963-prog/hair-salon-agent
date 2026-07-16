from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.database.connection import SessionLocal
from backend.database.models import User, UserRole
from backend.main import app


client = TestClient(app)


def _headers(role: UserRole, password: str) -> dict[str, str]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.role == role).first()
        user.password_hash = hash_password(password)
        phone = user.phone
        db.commit()
    finally:
        db.close()
    login = client.post("/api/auth/login", json={"phone": phone, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_employee_cannot_read_financially_sensitive_marketing_or_retention_data():
    employee_headers = _headers(UserRole.STYLIST, "EmployeePass123!")
    manager_headers = _headers(UserRole.ADMIN, "ManagerPass123!")

    assert client.get("/api/marketing/birthdays", headers=employee_headers).status_code == 403
    assert client.get("/api/retention/tasks?view=today", headers=employee_headers).status_code == 403
    assert client.get("/api/marketing/birthdays", headers=manager_headers).status_code == 200
    assert client.get("/api/retention/tasks?view=today", headers=manager_headers).status_code == 200

    audits = client.get("/api/audit-logs", headers=manager_headers).json()
    denied_paths = [item["details"] or "" for item in audits if item["action"] == "security.permission_denied"]
    assert any("/api/marketing/birthdays" in item for item in denied_paths)
    assert any("/api/retention/tasks" in item for item in denied_paths)
