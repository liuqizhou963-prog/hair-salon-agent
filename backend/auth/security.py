"""Password hashing, JWT creation, and FastAPI identity dependencies."""

from datetime import datetime, timedelta, timezone
import json
from typing import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.connection import SessionLocal, get_db
from backend.database.models import AuditLog, User, UserRole


password_hasher = PasswordHash.recommended()
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    return bool(password_hash and password_hasher.verify(password, password_hash))


def create_access_token(user: User) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.AUTH_SECRET_KEY, algorithm="HS256")


def _auth_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已失效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = None
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    if token is None:
        token = request.cookies.get("access_token")
    if not token:
        raise _auth_error()

    try:
        payload = jwt.decode(
            token,
            settings.AUTH_SECRET_KEY,
            algorithms=["HS256"],
        )
        user_id = payload.get("sub")
        if not user_id:
            raise _auth_error()
    except (jwt.InvalidTokenError, ValueError):
        raise _auth_error()

    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user:
        raise _auth_error()
    return user


def require_roles(*roles: UserRole) -> Callable:
    def dependency(request: Request, user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            _record_permission_denied(user, roles, request.url.path)
            raise HTTPException(status_code=403, detail="没有执行该操作的权限")
        return user

    return dependency


require_customer = require_roles(UserRole.CUSTOMER)
require_staff = require_roles(UserRole.STYLIST, UserRole.ADMIN)
require_admin = require_roles(UserRole.ADMIN)


def _record_permission_denied(user: User, required_roles: tuple[UserRole, ...], path: str) -> None:
    """Keep denied requests auditable without relying on an endpoint handler."""
    db = SessionLocal()
    try:
        db.add(AuditLog(
            actor_user_id=user.id,
            action="security.permission_denied",
            entity_type="api_route",
            entity_id=str(user.id),
            details=json.dumps({
                "path": path,
                "actual_role": user.role.value,
                "required_roles": [role.value for role in required_roles],
            }, ensure_ascii=False),
        ))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
