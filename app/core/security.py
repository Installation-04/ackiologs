from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select

from app.config import get_settings
from app.core.runtime_settings import runtime_settings
from app.db.base import session_scope
from app.db.models import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("ascii"))
    except ValueError:
        return False


def create_access_token(subject: str, role: str) -> str:
    settings = get_settings()
    expire_minutes = runtime_settings.get("security.access_token_expire_minutes")
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


async def authenticate_user(username: str, password: str) -> User | None:
    async with session_scope() as session:
        user = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if user is None or user.disabled or not verify_password(password, user.hashed_password):
            return None
        return user


class CurrentUser:
    def __init__(self, username: str, role: Role) -> None:
        self.username = username
        self.role = role


def verify_token(token: str | None) -> CurrentUser | None:
    """Shared JWT check used by both the HTTP dependency and the WebSocket route below
    — WebSocket connections can't carry an Authorization header from a browser client,
    so /ws/live takes the token as a query parameter and verifies it the same way."""
    settings = get_settings()
    if not settings.auth_enabled:
        return CurrentUser(username="anonymous", role=Role.ADMIN)
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        username = payload.get("sub")
        role = payload.get("role")
        if username is None or role is None:
            return None
        return CurrentUser(username=username, role=Role(role))
    except (JWTError, ValueError):
        return None


async def get_current_user(token: Annotated[str | None, Depends(oauth2_scheme)]) -> CurrentUser:
    user = verify_token(token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*roles: Role):
    async def checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if roles and user.role not in roles and user.role != Role.ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return checker


async def ensure_default_admin() -> None:
    """First-run convenience: create an `admin` user with a random password if none exists,
    printed once to the log so a fresh deployment is usable immediately."""
    import secrets

    async with session_scope() as session:
        count = (await session.execute(select(User))).first()
        if count is not None:
            return
        password = secrets.token_urlsafe(12)
        session.add(User(username="admin", hashed_password=hash_password(password), role=Role.ADMIN))
        await session.commit()
        import logging

        logging.getLogger("ackiologs").warning(
            "Created default admin user -> username='admin' password='%s' "
            "(rotate this immediately: update the users table, or delete the row and restart to regenerate it)",
            password,
        )
