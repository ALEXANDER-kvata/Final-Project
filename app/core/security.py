from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.exceptions import BadRequestError
from app.models.user import User

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

INVITE_TOKEN_PURPOSE = "invite"


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return password_context.verify(plain_password, password_hash)


def create_access_token(user_id: int) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_invite_token(project_id: int) -> tuple[str, datetime]:
    """Sign a share link that grants access to one project for a limited time.

    The ``purpose`` claim keeps invite tokens and access tokens apart even
    though both are signed with the same secret.
    """
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.invite_token_expire_minutes)
    payload = {
        "project_id": project_id,
        "purpose": INVITE_TOKEN_PURPOSE,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_invite_token(token: str) -> int:
    invalid_invite = BadRequestError("Invite link is invalid or has expired")

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise invalid_invite from exc

    if payload.get("purpose") != INVITE_TOKEN_PURPOSE:
        raise invalid_invite

    project_id = payload.get("project_id")
    if not isinstance(project_id, int):
        raise invalid_invite

    return project_id


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = int(payload.get("sub", ""))
    except (JWTError, ValueError) as exc:
        raise credentials_error from exc

    user = await db.get(User, user_id)
    if user is None:
        raise credentials_error

    return user
