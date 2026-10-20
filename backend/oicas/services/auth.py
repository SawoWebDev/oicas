"""Login with Odoo (server-side credential check, group → role mapping) and break-glass login."""
from __future__ import annotations

import threading
import time
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import security
from ..config import get_settings
from ..models import User
from ..odoo.client import OdooError, OdooGateway
from . import audit, rules


class AuthError(Exception):
    pass


class _Throttle:
    """At most ``limit`` failures per (login, ip) within ``window`` seconds."""

    def __init__(self, limit: int = 5, window: int = 900):
        self.limit, self.window = limit, window
        self._fails: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def blocked(self, key: tuple[str, str]) -> bool:
        with self._lock:
            now = time.monotonic()
            self._fails[key] = [t for t in self._fails[key] if now - t < self.window]
            return len(self._fails[key]) >= self.limit

    def fail(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._fails[key].append(time.monotonic())

    def reset(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._fails.pop(key, None)


throttle = _Throttle()


def role_for_groups(db: Session, groups: list[str]) -> str | None:
    mapping: dict = rules.get_setting(db, "auth_group_role_map") or {}
    best = None
    for g in groups:
        r = mapping.get(g)
        if r and security.role_rank(r) > security.role_rank(best or ""):
            best = r
    return best or rules.get_setting(db, "auth_default_role")


def login_with_odoo(db: Session, gw: OdooGateway, login: str, password: str, ip: str | None,
                    user_agent: str | None) -> tuple[User, str]:
    login = (login or "").strip()
    key = (login.lower(), ip or "")
    if not login or not password:
        raise AuthError("Enter your Odoo login and password.")
    if throttle.blocked(key):
        raise AuthError("Too many failed attempts. Try again in 15 minutes.")
    try:
        uid = gw.authenticate(login, password)
    except OdooError as e:
        audit.record(db, None, "auth.odoo_unavailable", "app_user", None, {"login": login, "error": str(e)}, ip)
        raise AuthError("Odoo is unreachable, so sign-in can't be verified right now. Try again later.") from e
    if not uid:
        throttle.fail(key)
        audit.record(db, None, "auth.failed", "app_user", None, {"login": login}, ip)
        raise AuthError("Invalid Odoo login or password.")
    info = gw.user_info(uid)
    if info.get("share") or not info.get("active", True):
        audit.record(db, None, "auth.denied", "app_user", None, {"login": login, "reason": "portal/inactive"}, ip)
        raise AuthError("Your Odoo account is not an internal user, so it can't access OICAS.")
    role = role_for_groups(db, info.get("groups", []))
    user = db.scalars(select(User).where(User.odoo_uid == uid)).first() or \
        db.scalars(select(User).where(User.login == info["login"])).first()
    if user is None:
        if not role:
            raise AuthError("Your Odoo groups don't grant access to OICAS.")
        user = User(login=info["login"], odoo_uid=uid, role=role, active=True, role_locked=False)
        db.add(user)
    user.odoo_uid, user.name, user.email = uid, info.get("name") or info["login"], info.get("email")
    if not user.role_locked and role:
        user.role = role
    if not user.active:
        raise AuthError("Your OICAS access has been disabled by an administrator.")
    db.flush()
    throttle.reset(key)
    token = security.create_session(db, user, ip, user_agent, "odoo")
    audit.record(db, user, "auth.login", "app_user", user.id, {"method": "odoo", "role": user.role,
                                                               "groups": info.get("groups")}, ip)
    return user, token


def login_local(db: Session, login: str, password: str, ip: str | None, user_agent: str | None) -> tuple[User, str]:
    key = ((login or "").lower(), ip or "")
    if throttle.blocked(key):
        raise AuthError("Too many failed attempts. Try again in 15 minutes.")
    user = db.scalars(select(User).where(User.login == login, User.local_password_hash.isnot(None))).first()
    if user is None or not user.active or not security.verify_password(password, user.local_password_hash):
        throttle.fail(key)
        audit.record(db, None, "auth.failed", "app_user", None, {"login": login, "method": "local"}, ip)
        raise AuthError("Invalid login or password.")
    throttle.reset(key)
    token = security.create_session(db, user, ip, user_agent, "local")
    audit.record(db, user, "auth.login", "app_user", user.id, {"method": "local"}, ip)
    return user, token


def ensure_bootstrap_admin(db: Session) -> None:
    s = get_settings()
    if not (s.bootstrap_admin_login and s.bootstrap_admin_password):
        return
    user = db.scalars(select(User).where(User.login == s.bootstrap_admin_login)).first()
    if user is None:
        user = User(login=s.bootstrap_admin_login, name="Break-glass administrator", role="admin", role_locked=True)
        db.add(user)
    if not security.verify_password(s.bootstrap_admin_password, user.local_password_hash):
        user.local_password_hash = security.hash_password(s.bootstrap_admin_password)
