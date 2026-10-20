"""In-memory store of the logged-in user's ERP (Odoo) credentials, per OICAS session.

Lets a user run an Odoo sync with their own ERP login, without API keys or a service account.
Credentials are kept ONLY in this process's memory: never written to the database, disk or logs.
They expire with the OICAS session and are removed on logout or revocation. After a server
restart the store is empty and the user is simply asked for their ERP password again.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ErpCredentials:
    uid: int
    login: str
    secret: str
    expires: float

    def __repr__(self) -> str:  # never leak the secret in logs or tracebacks
        return f"ErpCredentials(uid={self.uid}, login={self.login!r}, secret=***)"


_store: dict[str, ErpCredentials] = {}
_lock = threading.Lock()


def put(session_id: str, uid: int, login: str, secret: str, ttl_seconds: float) -> None:
    with _lock:
        _store[session_id] = ErpCredentials(uid, login, secret, time.monotonic() + ttl_seconds)


def get(session_id: str | None) -> ErpCredentials | None:
    if not session_id:
        return None
    with _lock:
        c = _store.get(session_id)
        if c and c.expires <= time.monotonic():
            _store.pop(session_id, None)
            return None
        return c


def drop(session_id: str | None) -> None:
    with _lock:
        _store.pop(session_id or "", None)


def clear() -> None:
    with _lock:
        _store.clear()
