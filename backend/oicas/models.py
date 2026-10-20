"""Relational data model (docs/architecture.md §Data model, docs/analysis/06-source-to-target-mapping.md).

Conventions
- Quantities are double precision (same arithmetic as Excel/Odoo float); ``NULL`` = unknown,
  ``0`` = confirmed zero. They are never interchanged.
- History is append-only: counts, snapshots, analysis runs, rule sets and audit rows are never
  overwritten. Corrections supersede.
- ``item.code`` is the business key; ``item.odoo_product_id`` is the stable Odoo key.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


TS = DateTime(timezone=True)


# ------------------------------------------------------------------ identity & access
class User(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str | None] = mapped_column(String(200))
    odoo_uid: Mapped[int | None] = mapped_column(Integer, unique=True)
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    role_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # admin override of group mapping
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    local_password_hash: Mapped[str | None] = mapped_column(String(300))  # break-glass only (scrypt)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(TS)


class AuthSession(Base):
    __tablename__ = "auth_session"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the cookie token
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TS)
    last_seen_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    auth_method: Mapped[str] = mapped_column(String(20), default="odoo")
    user: Mapped[User] = relationship()


# ------------------------------------------------------------------ Odoo reference data
class StockLocation(Base):
    __tablename__ = "stock_location"
    id: Mapped[int] = mapped_column(primary_key=True)
    odoo_id: Mapped[int] = mapped_column(Integer, unique=True)
    complete_name: Mapped[str] = mapped_column(String(300))
    usage: Mapped[str] = mapped_column(String(30), default="internal")
    company_name: Mapped[str | None] = mapped_column(String(200))
    warehouse_name: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    bucket: Mapped[str | None] = mapped_column(String(20))  # WAREHOUSE / PRODUCTION / IGNORE / NULL=unmapped
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class Item(Base):
    __tablename__ = "item"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True)
    odoo_product_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    uom_name: Mapped[str | None] = mapped_column(String(60))
    odoo_active: Mapped[bool | None] = mapped_column(Boolean)
    # application-owned attributes
    abc_family: Mapped[str | None] = mapped_column(String(80), index=True)
    material_section: Mapped[str | None] = mapped_column(String(80), index=True)
    plant_location: Mapped[str | None] = mapped_column(String(40))
    remark: Mapped[str | None] = mapped_column(String(300))
    is_jit: Mapped[bool] = mapped_column(Boolean, default=False)
    tracked: Mapped[bool] = mapped_column(Boolean, default=True)  # part of the cycle-count masterlist
    source: Mapped[str] = mapped_column(String(20), default="odoo")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(TS)


class ItemFamily(Base):
    """ABC family membership (an item may belong to several legacy family sheets, DQ-03)."""
    __tablename__ = "item_family"
    __table_args__ = (UniqueConstraint("item_code", "family"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_code: Mapped[str] = mapped_column(String(120), index=True)
    family: Mapped[str] = mapped_column(String(80))


class UomAlias(Base):
    __tablename__ = "uom_alias"
    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(60), unique=True)
    canonical: Mapped[str] = mapped_column(String(60))


# ------------------------------------------------------------------ synchronisation & snapshots
class SyncRun(Base):
    __tablename__ = "sync_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # inventory / demand / import
    mode: Mapped[str] = mapped_column(String(10))  # live / fake / file
    status: Mapped[str] = mapped_column(String(20), default="running")  # running/success/partial/failed
    started_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    triggered_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshot"
    id: Mapped[int] = mapped_column(primary_key=True)
    sync_run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_run.id"))
    taken_at: Mapped[datetime] = mapped_column(TS, index=True)
    source: Mapped[str] = mapped_column(String(20))  # odoo / excel_import / legacy_list
    label: Mapped[str] = mapped_column(String(200), default="")
    complete: Mapped[bool] = mapped_column(Boolean, default=False)  # all products & mapped locations read
    line_count: Mapped[int] = mapped_column(Integer, default=0)


class SnapshotLine(Base):
    """Bucket balance per item. For complete snapshots a missing line means 0 for known products."""
    __tablename__ = "snapshot_line"
    __table_args__ = (UniqueConstraint("snapshot_id", "item_code", "bucket"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("inventory_snapshot.id", ondelete="CASCADE"), index=True)
    item_code: Mapped[str] = mapped_column(String(120), index=True)
    bucket: Mapped[str] = mapped_column(String(20))
    qty: Mapped[float] = mapped_column(Float)


class SnapshotQuant(Base):
    """Raw per-location quantities (audit trail; lets buckets be re-derived after re-mapping)."""
    __tablename__ = "snapshot_quant"
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("inventory_snapshot.id", ondelete="CASCADE"), index=True)
    item_code: Mapped[str] = mapped_column(String(120))
    location_odoo_id: Mapped[int] = mapped_column(Integer)
    qty: Mapped[float] = mapped_column(Float)


# ------------------------------------------------------------------ demand, rules, analysis
class DemandBatch(Base):
    __tablename__ = "demand_batch"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))  # odoo / excel
    label: Mapped[str] = mapped_column(String(200))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    sync_run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_run.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class DemandLine(Base):
    __tablename__ = "demand_line"
    __table_args__ = (UniqueConstraint("batch_id", "item_code", "month"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("demand_batch.id", ondelete="CASCADE"), index=True)
    item_code: Mapped[str] = mapped_column(String(120))
    month: Mapped[date] = mapped_column(Date)
    qty: Mapped[float] = mapped_column(Float)


class RuleSet(Base):
    """Versioned calculation parameters (thresholds, CLASS matrix, tolerances, policies)."""
    __tablename__ = "rule_set"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(120))
    effective_from: Mapped[date] = mapped_column(Date)
    params: Mapped[dict] = mapped_column(JSON)
    class_matrix: Mapped[dict] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class AnalysisRun(Base):
    __tablename__ = "analysis_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), default="engine")  # engine / legacy_import
    period_start: Mapped[date] = mapped_column(Date)
    months: Mapped[int] = mapped_column(Integer)
    demand_batch_id: Mapped[int | None] = mapped_column(ForeignKey("demand_batch.id"))
    rule_set_id: Mapped[int] = mapped_column(ForeignKey("rule_set.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft / approved / superseded / rejected
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    approved_at: Mapped[datetime | None] = mapped_column(TS)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    rule_set: Mapped[RuleSet] = relationship()


class AnalysisResult(Base):
    __tablename__ = "analysis_result"
    __table_args__ = (UniqueConstraint("run_id", "item_code", "family"), Index("ix_ar_run_primary", "run_id", "is_primary"))
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_run.id", ondelete="CASCADE"), index=True)
    item_code: Mapped[str] = mapped_column(String(120), index=True)
    family: Mapped[str] = mapped_column(String(80))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    monthly: Mapped[list] = mapped_column(JSON)
    total: Mapped[float] = mapped_column(Float)
    share: Mapped[float] = mapped_column(Float)
    frequency: Mapped[int] = mapped_column(Integer)
    frequency_pct: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)
    cum_items_pct: Mapped[float] = mapped_column(Float)
    cum_demand_pct: Mapped[float] = mapped_column(Float)
    qty_class: Mapped[str] = mapped_column(String(1))
    freq_class: Mapped[str] = mapped_column(String(1))
    category: Mapped[str] = mapped_column(String(2))
    declared_type: Mapped[str | None] = mapped_column(String(10))
    action: Mapped[str | None] = mapped_column(String(40))
    classification: Mapped[str | None] = mapped_column(String(30))
    interval_days: Mapped[int | None] = mapped_column(Integer)
    amc: Mapped[float] = mapped_column(Float)


# ------------------------------------------------------------------ counting
class CountPlan(Base):
    __tablename__ = "count_plan"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    plan_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / closed / cancelled
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    items: Mapped[list["CountPlanItem"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class CountPlanItem(Base):
    __tablename__ = "count_plan_item"
    __table_args__ = (UniqueConstraint("plan_id", "item_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("count_plan.id", ondelete="CASCADE"), index=True)
    item_code: Mapped[str] = mapped_column(String(120))
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(40), default="scheduled")  # scheduled/overdue/never_counted/recount/manual
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / counted / skipped
    plan: Mapped[CountPlan] = relationship(back_populates="items")


class CountSession(Base):
    __tablename__ = "count_session"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("count_plan.id"))
    count_date: Mapped[date] = mapped_column(Date, index=True)
    counted_by_name: Mapped[str] = mapped_column(String(200))
    counter_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft/submitted/finalized/cancelled
    source: Mapped[str] = mapped_column(String(20), default="app")  # app / excel_upload / legacy_import
    client_token: Mapped[str | None] = mapped_column(String(64), unique=True)  # idempotency key
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_snapshot.id"))
    recount_of_reconciliation_id: Mapped[int | None] = mapped_column(Integer)
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(TS)
    finalized_at: Mapped[datetime | None] = mapped_column(TS)
    finalized_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    entries: Mapped[list["CountEntry"]] = relationship(back_populates="session")


class CountEntry(Base):
    """One physical count figure. Never updated after submission: corrections supersede."""
    __tablename__ = "count_entry"
    __table_args__ = (Index("ix_entry_item_session", "item_code", "session_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("count_session.id"), index=True)
    item_code: Mapped[str] = mapped_column(String(120))
    bucket: Mapped[str] = mapped_column(String(20))  # WAREHOUSE / PRODUCTION
    slot: Mapped[str] = mapped_column(String(20), default="1")  # WH-1..4 / PROD-1..4 (UD-07)
    round: Mapped[int] = mapped_column(Integer, default=1)
    qty: Mapped[float] = mapped_column(Float)
    uom_name: Mapped[str | None] = mapped_column(String(60))
    remarks: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("count_entry.id"))
    superseded_at: Mapped[datetime | None] = mapped_column(TS)
    correction_reason: Mapped[str | None] = mapped_column(String(500))
    session: Mapped[CountSession] = relationship(back_populates="entries")


class Reconciliation(Base):
    """Physical vs Odoo for one item on one count date. Recalculation supersedes (history kept)."""
    __tablename__ = "reconciliation"
    __table_args__ = (Index("ix_recon_current", "item_code", "superseded", "count_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_code: Mapped[str] = mapped_column(String(120))
    count_date: Mapped[date] = mapped_column(Date, index=True)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_snapshot.id"))
    rule_set_id: Mapped[int | None] = mapped_column(ForeignKey("rule_set.id"))
    # where the system balance came from: odoo / legacy / book (imported book balance, item not in Odoo)
    balance_source: Mapped[str | None] = mapped_column(String(10))
    phys_wh: Mapped[float | None] = mapped_column(Float)
    phys_prod: Mapped[float | None] = mapped_column(Float)
    odoo_wh: Mapped[float | None] = mapped_column(Float)
    odoo_prod: Mapped[float | None] = mapped_column(Float)
    disc_wh: Mapped[float | None] = mapped_column(Float)
    disc_prod: Mapped[float | None] = mapped_column(Float)
    has_discrepancy: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20))  # engine status
    review_status: Mapped[str] = mapped_column(String(20), default="open")  # open/recount_requested/investigating/resolved/n_a
    classification_at_count: Mapped[str | None] = mapped_column(String(30))
    counted_by: Mapped[str | None] = mapped_column(String(300))
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("reconciliation.id"))
    computed_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class DiscrepancyNote(Base):
    __tablename__ = "discrepancy_note"
    id: Mapped[int] = mapped_column(primary_key=True)
    reconciliation_id: Mapped[int] = mapped_column(ForeignKey("reconciliation.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))  # comment/recount_requested/investigating/resolved/reopened
    note: Mapped[str] = mapped_column(Text, default="")
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


# ------------------------------------------------------------------ governance
class DqException(Base):
    __tablename__ = "dq_exception"
    __table_args__ = (UniqueConstraint("kind", "ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    ref: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(10), default="warning")  # info/warning/error
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / resolved / ignored
    source: Mapped[str] = mapped_column(String(40), default="")
    first_seen_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(TS)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    user_login: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(120))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))


class ReportRun(Base):
    __tablename__ = "report_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_key: Mapped[str] = mapped_column(String(40), index=True)
    fmt: Mapped[str] = mapped_column(String(10))  # xlsx / pdf
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_id: Mapped[int | None] = mapped_column(Integer)
    analysis_run_id: Mapped[int | None] = mapped_column(Integer)
    rule_set_id: Mapped[int | None] = mapped_column(Integer)
    file_name: Mapped[str] = mapped_column(String(300), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class AppSetting(Base):
    """Non-calculation settings (lists, role map, retention). Changes are audited."""
    __tablename__ = "app_setting"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
