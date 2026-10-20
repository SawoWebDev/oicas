"""Roles, permissions, server-side sessions, CSRF and the break-glass password hash.

Authorization is always enforced on the backend (route dependencies call ``require``).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AuthSession, User

ROLES = ("viewer", "counter", "manager", "admin")

# permission -> minimum role
PERMISSIONS: dict[str, str] = {
    "view": "viewer",  # dashboard, masterlist, reports, exports
    "count.enter": "counter",  # create sessions, enter & submit counts
    "count.finalize": "manager",  # finalize sessions, corrections after submission, recounts
    "plan.manage": "manager",
    "discrepancy.review": "manager",
    "item.edit": "manager",  # application-owned item attributes
    "sync.run": "manager",
    "analysis.run": "manager",
    "analysis.approve": "manager",
    "import.run": "manager",
    "dq.resolve": "manager",
    "audit.view": "manager",
    "config.manage": "admin",  # rule sets, settings, location mapping
    "users.manage": "admin",
}


def role_rank(role: str) -> int:
    return ROLES.index(role) if role in ROLES else -1


def has_permission(user: User | None, perm: str) -> bool:
    if user is None or not user.active:
        return False
    need = PERMISSIONS.get(perm)
    if need is None:
        raise KeyError(f"unknown permission {perm}")
    return role_rank(user.role) >= role_rank(need)


# ------------------------------------------------------------------ password hashing (scrypt)
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                            dklen=len(bytes.fromhex(digest)))
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------------ sessions
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_id(token: str) -> str:
    return _hash_token(token)


def _forget_erp(session_ids) -> None:
    from .odoo import vault
    for sid in session_ids:
        vault.drop(sid)


def create_session(db: Session, user: User, ip: str | None, user_agent: str | None, method: str) -> str:
    s = get_settings()
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.add(AuthSession(id=_hash_token(token), user_id=user.id, csrf_token=secrets.token_urlsafe(24),
                       created_at=now, last_seen_at=now, expires_at=now + timedelta(hours=s.session_hours),
                       ip=ip, user_agent=(user_agent or "")[:300], auth_method=method))
    user.last_login_at = now
    db.flush()
    return token


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_session(db: Session, token: str | None) -> AuthSession | None:
    if not token:
        return None
    sess = db.get(AuthSession, _hash_token(token))
    if sess is None or sess.revoked_at is not None:
        return None
    now = datetime.now(timezone.utc)
    idle = timedelta(minutes=get_settings().session_idle_minutes)
    if _aware(sess.expires_at) <= now or _aware(sess.last_seen_at) + idle <= now:
        sess.revoked_at = now
        _forget_erp([sess.id])
        db.flush()
        return None
    if not sess.user.active:
        return None
    if (now - _aware(sess.last_seen_at)).total_seconds() > 60:
        sess.last_seen_at = now
    return sess


def revoke_session(db: Session, token: str | None) -> None:
    if token:
        _forget_erp([_hash_token(token)])
        sess = db.get(AuthSession, _hash_token(token))
        if sess and sess.revoked_at is None:
            sess.revoked_at = datetime.now(timezone.utc)


def revoke_user_sessions(db: Session, user_id: int) -> None:
    _forget_erp(db.scalars(select(AuthSession.id).where(AuthSession.user_id == user_id)))
    db.execute(update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))


def active_sessions(db: Session) -> list[AuthSession]:
    now = datetime.now(timezone.utc)
    return list(db.scalars(select(AuthSession).where(AuthSession.revoked_at.is_(None), AuthSession.expires_at > now)
                           .order_by(AuthSession.last_seen_at.desc())))


def csrf_ok(sess: AuthSession, supplied: str | None) -> bool:
    return bool(supplied) and hmac.compare_digest(sess.csrf_token, supplied or "")
