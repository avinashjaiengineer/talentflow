from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Role, User
from ..schemas import UserOut
from ..security import create_session_token, hash_password, login_limiter, verify_password
from .deps import SESSION_COOKIE, current_user, require_admin

router = APIRouter(tags=["auth"])

# Equalize timing between "no such user" and "wrong password".
_DUMMY_HASH = hash_password("timing-equalizer")


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class LoginOut(BaseModel):
    user: UserOut
    token: str  # for API clients; the browser uses the httpOnly cookie


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=10, max_length=200)
    role: Role = Role.recruiter


class UserUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=10, max_length=200)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE, token, max_age=s.session_hours * 3600, httponly=True, secure=s.cookie_secure, samesite="lax", path="/"
    )


@router.post("/auth/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    key = _client_key(request)
    if login_limiter.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed sign-in attempts; try again in 15 minutes")
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not (user and ok and user.is_active):
        login_limiter.record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    login_limiter.reset(key)
    user.last_login_at = datetime.now(UTC)
    db.commit()
    token = create_session_token(user.id, user.token_version)
    _set_cookie(response, token)
    return LoginOut(user=UserOut.model_validate(user), token=token)


@router.post("/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.post("/auth/password", status_code=204)
def change_password(body: PasswordChange, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # sign out other sessions
    db.commit()
    _set_cookie(response, create_session_token(user.id, user.token_version))


# ---------------------------------------------------------------- user admin


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.created_at)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists")
    user = User(email=body.email.lower(), name=body.name, password_hash=hash_password(body.password), role=body.role)
    db.add(user)
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and (body.is_active is False or body.role == Role.recruiter):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't deactivate or demote yourself")
    if body.name is not None:
        user.name = body.name
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
        user.token_version += 1
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        user.token_version += 1
    db.commit()
    return user


def ensure_bootstrap_admin(db: Session) -> None:
    """Create the first admin from ADMIN_EMAIL / ADMIN_PASSWORD when the users table is empty."""
    s = get_settings()
    if not (s.admin_email and s.admin_password) or db.scalar(select(func.count()).select_from(User)):
        return
    db.add(User(email=s.admin_email.lower(), name=s.admin_name, password_hash=hash_password(s.admin_password), role=Role.admin))
    try:
        db.commit()
    except IntegrityError:  # another server process created it first
        db.rollback()
