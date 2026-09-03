from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from backend.db import DataSource, DataSourceField, SessionLocal
from backend.services.client_fields import canonical_client_field_key

SUPPORTED_SOURCE_TYPES = {"excel", "google_sheets"}


class DataSourceError(ValueError):
    pass


def _field_id(source_id: str, reference: str) -> str:
    digest = hashlib.sha256(f"{source_id}:{reference}".encode()).hexdigest()[:24]
    return f"field-{digest}"


def _dump_field(field: DataSourceField) -> dict[str, Any]:
    return {
        "id": field.id,
        "field_id": field.id,
        "data_source_id": field.data_source_id,
        "display_name": field.display_name,
        "source_column_reference": field.source_column_reference,
        "semantic_role": field.semantic_role,
        "data_type": field.data_type,
        "active": field.active,
    }


def _dump_source(source: DataSource, fields: list[DataSourceField] | None = None) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "type": source.source_type,
        "source_type": source.source_type,
        "status": source.status,
        "schema": source.schema_metadata or {},
        "configuration": source.configuration or {},
        "fields": [_dump_field(field) for field in (fields or [])],
    }


def upsert_source_schema(*, name: str, source_type: str, headers: list[str], configuration: dict[str, Any] | None = None) -> dict[str, Any]:
    source_type = str(source_type).strip().lower()
    if source_type not in SUPPORTED_SOURCE_TYPES:
        raise DataSourceError("Tipo de fonte não suportado.")
    clean_headers = [str(header).strip() for header in headers if str(header).strip()]
    with SessionLocal() as db:
        source = db.scalar(select(DataSource).where(DataSource.name == name, DataSource.source_type == source_type))
        if source is None:
            source = DataSource(id=str(uuid4()), name=name.strip() or source_type, source_type=source_type)
            db.add(source)
            db.flush()
        source.schema_metadata = {"headers": clean_headers, "version": int((source.schema_metadata or {}).get("version", 0)) + 1}
        if configuration:
            source.configuration = {**(source.configuration or {}), **{str(k): v for k, v in configuration.items() if k not in {"token", "secret", "password", "credentials"}}}
        existing = {field.source_column_reference: field for field in db.scalars(select(DataSourceField).where(DataSourceField.data_source_id == source.id))}
        for index, header in enumerate(clean_headers):
            # Column position is the source identity; the display label may be renamed.
            reference = f"column:{index}"
            field = existing.get(reference)
            if field is None:
                field = DataSourceField(id=_field_id(source.id, reference), data_source_id=source.id, display_name=header, source_column_reference=reference, semantic_role=canonical_client_field_key(header))
                db.add(field)
            else:
                field.display_name = header
                field.semantic_role = canonical_client_field_key(header)
                field.active = True
        db.commit()
        db.refresh(source)
        fields = list(db.scalars(select(DataSourceField).where(DataSourceField.data_source_id == source.id).order_by(DataSourceField.created_at, DataSourceField.id)))
        return _dump_source(source, fields)


def list_sources() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        sources = list(db.scalars(select(DataSource).order_by(DataSource.created_at.desc())))
        fields = list(db.scalars(select(DataSourceField).where(DataSourceField.active.is_(True))))
        by_source: dict[str, list[DataSourceField]] = {}
        for field in fields:
            by_source.setdefault(field.data_source_id, []).append(field)
        return [_dump_source(source, by_source.get(source.id, [])) for source in sources]


def get_source(source_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        source = db.get(DataSource, source_id)
        if source is None:
            return None
        fields = list(db.scalars(select(DataSourceField).where(DataSourceField.data_source_id == source.id, DataSourceField.active.is_(True)).order_by(DataSourceField.created_at)))
        return _dump_source(source, fields)
