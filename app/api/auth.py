from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.security import create_access_token, get_current_user, hash_password, verify_password
from app.models.user import User
from app.schemas.user import TokenOut, UserCreate, UserLogin, UserOut

router = APIRouter(tags=["auth"])


async def read_login_payload(request: Request) -> UserLogin:
    content_type = request.headers.get("content-type", "")
    try:
        is_form_request = (
            "application/x-www-form-urlencoded" in content_type
            or "multipart/form-data" in content_type
        )
        if is_form_request:
            form = await request.form()
            return UserLogin.model_validate(
                {
                    "login": form.get("username") or form.get("login"),
                    "password": form.get("password"),
                }
            )

        return UserLogin.model_validate(await request.json())
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc


@router.post("/auth", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    existing_user = await db.scalar(select(User).where(User.login == payload.login))
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Login is already registered",
        )

    user = User(login=payload.login, password_hash=hash_password(payload.password))
    db.add(user)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Login is already registered",
        ) from exc

    await db.refresh(user)
    return user


@router.post(
    "/login",
    response_model=TokenOut,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": UserLogin.model_json_schema(),
                },
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "username": {"type": "string", "description": "Same as 'login'"},
                            "password": {"type": "string"},
                        },
                        "required": ["username", "password"],
                    },
                },
            },
            "required": True,
        }
    },
)
async def login_user(
    payload: Annotated[UserLogin, Depends(read_login_payload)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenOut:
    user = await db.scalar(select(User).where(User.login == payload.login))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid login or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenOut(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
async def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user
