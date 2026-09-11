"""Repair only legacy OAuth entry URLs with an embedded first parameter."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from alembic import op
import sqlalchemy as sa


revision = "0025_normalize_entry_urls"
down_revision = "0024_access_cycle_session"
branch_labels = None
depends_on = None


def _normalize(value: object) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.query:
        return raw
    pairs = []
    changed = False
    for key, parameter_value in parse_qsl(parsed.query, keep_blank_values=True):
        embedded = urlsplit(key)
        embedded_pairs = parse_qsl(embedded.query, keep_blank_values=True)
        if not embedded_pairs and embedded.query and "=" not in embedded.query and "&" not in embedded.query:
            embedded_pairs = [(embedded.query, "")]
        if (
            embedded.scheme == parsed.scheme
            and embedded.netloc == parsed.netloc
            and embedded.path == parsed.path
            and len(embedded_pairs) == 1
            and embedded_pairs[0][1] == ""
        ):
            pairs.append((embedded_pairs[0][0], parameter_value))
            changed = True
        else:
            pairs.append((key, parameter_value))
    if not changed:
        return raw
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(pairs), parsed.fragment))


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, config FROM external_systems")).mappings().all()
    for row in rows:
        config = dict(row["config"] or {})
        entry = _normalize(config.get("entry_url"))
        login = _normalize(config.get("external_login_url"))
        if entry == str(config.get("entry_url") or "") and login == str(config.get("external_login_url") or ""):
            continue
        config["entry_url"] = entry
        config["external_login_url"] = login or entry
        connection.execute(
            sa.text("UPDATE external_systems SET config = CAST(:config AS jsonb) WHERE id = :id"),
            {"id": row["id"], "config": __import__("json").dumps(config)},
        )


def downgrade() -> None:
    # The corrected URL is semantically identical; recreating malformed data is unsafe.
    pass
