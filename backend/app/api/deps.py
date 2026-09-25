from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Role, User
from ..security import decode_session_token

SESSION_COOKIE = "tf_session"


def _token_from(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _token_from(request)
    claims = decode_session_token(token) if token else None
    user = db.get(User, claims["sub"]) if claims else None
    if user is None or not user.is_active or claims.get("ver") != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in", headers={"WWW-Authenticate": "Bearer"})
    request.state.user_id = user.id
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")
    return user
