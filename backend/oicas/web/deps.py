"""Request dependencies: DB session, authenticated user, permissions, CSRF."""
from __future__ import annotations

from typing import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .. import security
from ..db import session_factory
from ..models import AuthSession, User

COOKIE = "oicas_session"


class NotAuthenticated(Exception):
    pass


class Forbidden(Exception):
    def __init__(self, perm: str):
        self.perm = perm


class CsrfFailed(Exception):
    pass


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def current_session(request: Request, db: Session = Depends(get_db)) -> AuthSession:
    sess = security.load_session(db, request.cookies.get(COOKIE))
    db.commit()
    if sess is None:
        raise NotAuthenticated()
    request.state.auth = sess
    request.state.user = sess.user
    return sess


def current_user(sess: AuthSession = Depends(current_session)) -> User:
    return sess.user


def require(perm: str):
    def dep(user: User = Depends(current_user)) -> User:
        if not security.has_permission(user, perm):
            raise Forbidden(perm)
        return user
    return dep


async def check_csrf(request: Request, sess: AuthSession = Depends(current_session)) -> None:
    supplied = request.headers.get("X-CSRF-Token")
    if not supplied:
        form = await request.form()
        supplied = form.get("csrf")
    if not security.csrf_ok(sess, supplied):
        raise CsrfFailed()


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
