"""SQLAlchemy connection, models and persistence helpers for CotaSync."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def database_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://cotasync_test:cotasync_test_password@localhost:5432/cotasync_test",
    ).replace("postgresql://", "postgresql+psycopg://", 1)


engine = create_engine(database_url(), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    system_spreadsheet_id: Mapped[str | None] = mapped_column(String(128), index=True)
    list_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("client_lists.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    client_group: Mapped[str] = mapped_column(String(255), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    grupo: Mapped[str | None] = mapped_column(String(255))
    cota: Mapped[str | None] = mapped_column(String(255))
    versao: Mapped[str | None] = mapped_column(String(255))
    variables: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    schema_metadata: Mapped[dict[str, Any]] = mapped_column("schema_metadata", JSONB, default=dict)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DataSourceField(Base):
    __tablename__ = "data_source_fields"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    source_column_reference: Mapped[str] = mapped_column(String(255))
    semantic_role: Mapped[str | None] = mapped_column(String(64))
    data_type: Mapped[str] = mapped_column(String(32), default="string")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SpreadsheetConnector(Base):
    __tablename__ = "spreadsheet_connectors"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    spreadsheet_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)
    connector_type: Mapped[str] = mapped_column(String(32), index=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AISettings(Base):
    __tablename__ = "ai_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openai_compatible")
    model: Mapped[str] = mapped_column(String(255), nullable=False, default="gpt-4o-mini")
    base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ClientList(Base):
    __tablename__ = "client_lists"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="default")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="published")
    published_version_id: Mapped[str | None] = mapped_column(String(128))
    allowed_list_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ActionVersion(Base):
    __tablename__ = "action_versions"
    __table_args__ = (UniqueConstraint("action_id", "version_number", name="uq_action_version_number"),)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="published")
    created_by: Mapped[str | None] = mapped_column(String(255))
    source_version_id: Mapped[str | None] = mapped_column(String(128))
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    variables: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActionStep(Base):
    __tablename__ = "action_steps"
    __table_args__ = (UniqueConstraint("action_version_id", "step_index", name="uq_action_step_index"),)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    action_version_id: Mapped[str] = mapped_column(ForeignKey("action_versions.id", ondelete="CASCADE"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[str] = mapped_column(String(128), default="unknown")
    selector: Mapped[str | None] = mapped_column(Text)
    variable_key: Mapped[str | None] = mapped_column(String(255))
    step_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExtractionContract(Base):
    __tablename__ = "extraction_contracts"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    action_version_id: Mapped[str] = mapped_column(ForeignKey("action_versions.id", ondelete="CASCADE"), index=True)
    target_name: Mapped[str] = mapped_column(String(255))
    screen_label: Mapped[str] = mapped_column(String(255), default="")
    selection_type: Mapped[str] = mapped_column(String(64), default="text")
    value_type: Mapped[str] = mapped_column(String(64), default="string")
    return_format: Mapped[str] = mapped_column(String(64), default="text")
    selector_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    anchor_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    validation_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    example_value: Mapped[str | None] = mapped_column(Text)
    summary_instruction: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    action_id: Mapped[str | None] = mapped_column(ForeignKey("actions.id", ondelete="SET NULL"), index=True)
    action_version_id: Mapped[str | None] = mapped_column(ForeignKey("action_versions.id", ondelete="SET NULL"), index=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), index=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    run_origin: Mapped[str] = mapped_column(String(32), default="operational", index=True)
    runner: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_summary: Mapped[str | None] = mapped_column(Text)
    extracted_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    input_variables: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    step_trace: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    error_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    screenshot_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    action_id: Mapped[str | None] = mapped_column(ForeignKey("actions.id", ondelete="SET NULL"), index=True)
    action_version_id: Mapped[str | None] = mapped_column(ForeignKey("action_versions.id", ondelete="SET NULL"), index=True)
    client_group: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(64), index=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), index=True)
    delay_seconds: Mapped[float] = mapped_column(default=0)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    success_items: Mapped[int] = mapped_column(Integer, default=0)
    error_items: Mapped[int] = mapped_column(Integer, default=0)
    interrupted_items: Mapped[int] = mapped_column(Integer, default=0)
    cancelled_items: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    idempotency_user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    idempotency_operation: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_fingerprint: Mapped[str | None] = mapped_column(String(128))
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class BatchItem(Base):
    __tablename__ = "batch_items"
    __table_args__ = (UniqueConstraint("batch_id", "position", name="uq_batch_item_position"),)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    input_variables: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkerInstance(Base):
    __tablename__ = "worker_instances"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"), index=True)
    current_batch_item_id: Mapped[str | None] = mapped_column(ForeignKey("batch_items.id", ondelete="SET NULL"), index=True)
    hostname: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    action_id: Mapped[str | None] = mapped_column(ForeignKey("actions.id", ondelete="SET NULL"))
    client_group: Mapped[str | None] = mapped_column(String(255))
    frequency: Mapped[str] = mapped_column(String(128))
    timezone: Mapped[str] = mapped_column(String(128), default="UTC")
    schedule_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    delay_seconds: Mapped[float] = mapped_column(default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ExternalSystem(Base):
    __tablename__ = "external_systems"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DesktopViewToken(Base):
    __tablename__ = "desktop_view_tokens"
    digest: Mapped[str] = mapped_column(String(128), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
