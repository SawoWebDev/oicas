"""Read-only Odoo gateway (External API over XML-RPC).

Every model call goes through ``LiveOdoo._call``, which only lets read methods through. OICAS
cannot create, write, unlink or call business methods on Odoo (BR-27). Credentials stay on the
server; nothing here is ever sent to the browser.
"""
from __future__ import annotations

import http.client
import logging
import socket
import time
import xmlrpc.client
from typing import Iterator, Protocol

log = logging.getLogger("oicas.odoo")

READ_ONLY_METHODS = frozenset({"search_read", "read", "search", "search_count", "fields_get", "check_access_rights"})


class OdooError(Exception):
    """Odoo unreachable, rejected the call, or returned an unexpected payload."""


class ReadOnlyViolation(OdooError):
    """Attempt to call a non-read method. This is a programming error and is never retried."""


class OdooGateway(Protocol):
    mode: str

    def version(self) -> dict: ...

    def authenticate(self, login: str, password: str) -> int | None: ...

    def user_info(self, uid: int) -> dict: ...

    def search_read(self, model: str, domain: list, fields: list[str], order: str = "id") -> Iterator[dict]: ...


def assert_read_only(method: str) -> None:
    if method not in READ_ONLY_METHODS:
        raise ReadOnlyViolation(f"OICAS is read-only toward Odoo; method {method!r} is not allowed")


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: float):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


TRANSIENT = (socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException, OSError)


class LiveOdoo:
    mode = "live"

    def __init__(self, url: str, db: str, login: str, api_key: str, timeout: float = 60, page_size: int = 1000,
                 max_retries: int = 3):
        if not (url and db and login and api_key):
            raise OdooError("Odoo connection is not configured (ODOO_URL, ODOO_DB, ODOO_SYNC_LOGIN, ODOO_SYNC_API_KEY)")
        self.url, self.db, self.login, self._key = url.rstrip("/"), db, login, api_key
        self.page_size, self.max_retries = page_size, max_retries
        transport = _TimeoutSafeTransport(timeout) if self.url.startswith("https") else _TimeoutTransport(timeout)
        self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", transport=transport, allow_none=True)
        self._object = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", transport=transport, allow_none=True)
        self._uid: int | None = None
        self._groups_field: str | None = None

    # -- low level -------------------------------------------------------------------------
    def _retry(self, fn, what: str):
        delay = 1.0
        for attempt in range(1, self.max_retries + 1):
            try:
                return fn()
            except xmlrpc.client.Fault as e:  # Odoo-side error (access rights, bad domain): not transient
                raise OdooError(f"{what}: Odoo fault: {e.faultString.strip().splitlines()[-1] if e.faultString else e}") from e
            except xmlrpc.client.ProtocolError as e:
                if e.errcode < 500 or attempt == self.max_retries:
                    raise OdooError(f"{what}: HTTP {e.errcode} {e.errmsg}") from e
            except TRANSIENT as e:
                if attempt == self.max_retries:
                    raise OdooError(f"{what}: {type(e).__name__}: {e}") from e
            log.warning("Odoo %s failed (attempt %s/%s); retrying in %.0fs", what, attempt, self.max_retries, delay)
            time.sleep(delay)
            delay *= 2
        raise OdooError(f"{what}: retries exhausted")  # pragma: no cover

    def _service_uid(self) -> int:
        if self._uid is None:
            uid = self._retry(lambda: self._common.authenticate(self.db, self.login, self._key, {}), "authenticate")
            if not uid:
                raise OdooError("Odoo rejected the OICAS service account (check ODOO_SYNC_LOGIN / ODOO_SYNC_API_KEY)")
            self._uid = int(uid)
        return self._uid

    def _call(self, model: str, method: str, args: list, kwargs: dict | None = None):
        assert_read_only(method)
        uid = self._service_uid()
        return self._retry(lambda: self._object.execute_kw(self.db, uid, self._key, model, method, args, kwargs or {}),
                           f"{model}.{method}")

    # -- gateway API ----------------------------------------------------------------------
    def version(self) -> dict:
        return self._retry(lambda: self._common.version(), "version")

    def authenticate(self, login: str, password: str) -> int | None:
        """Validate an end user's Odoo credentials (password or API key). Nothing is stored."""
        uid = self._retry(lambda: self._common.authenticate(self.db, login, password, {}), "user authenticate")
        return int(uid) if uid else None

    def user_info(self, uid: int) -> dict:
        if self._groups_field is None:
            fields = self._call("res.users", "fields_get", [], {"attributes": ["type"]})
            self._groups_field = "groups_id" if "groups_id" in fields else "group_ids"
        rows = self._call("res.users", "read", [[uid]], {"fields": ["login", "name", "email", "share", "active",
                                                                     self._groups_field]})
        if not rows:
            raise OdooError(f"Odoo user {uid} not readable by the service account")
        u = rows[0]
        gids = u.get(self._groups_field) or []
        xmlids = [f"{r['module']}.{r['name']}" for r in self._call(
            "ir.model.data", "search_read", [[("model", "=", "res.groups"), ("res_id", "in", gids)]],
            {"fields": ["module", "name"]})]
        return {"uid": uid, "login": u["login"], "name": u.get("name") or u["login"], "email": u.get("email") or None,
                "share": bool(u.get("share")), "active": bool(u.get("active", True)), "groups": sorted(xmlids)}

    def search_read(self, model: str, domain: list, fields: list[str], order: str = "id") -> Iterator[dict]:
        """Paginated search_read (stable ``order``)."""
        offset = 0
        while True:
            page = self._call(model, "search_read", [domain],
                              {"fields": fields, "order": order, "limit": self.page_size, "offset": offset})
            if not isinstance(page, list):
                raise OdooError(f"{model}.search_read returned {type(page).__name__}")
            yield from page
            if len(page) < self.page_size:
                return
            offset += self.page_size


def gateway_from_settings() -> OdooGateway:
    from ..config import get_settings
    from .fake import FakeOdoo
    s = get_settings()
    if s.odoo_mode == "fake":
        return FakeOdoo.from_database()
    return LiveOdoo(s.odoo_url, s.odoo_db, s.odoo_sync_login, s.odoo_sync_api_key, s.odoo_timeout_seconds,
                    s.odoo_page_size, s.odoo_max_retries)
