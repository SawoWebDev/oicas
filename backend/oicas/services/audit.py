from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def _jsonable(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x) for x in v]
    return v


def record(db: Session, user: User | None, action: str, entity: str | None = None, entity_id: Any = None,
           detail: dict | None = None, ip: str | None = None) -> AuditLog:
    row = AuditLog(user_id=user.id if user else None, user_login=user.login if user else "system", action=action,
                   entity=entity, entity_id=None if entity_id is None else str(entity_id),
                   detail=_jsonable(detail or {}), ip=ip)
    db.add(row)
    return row
