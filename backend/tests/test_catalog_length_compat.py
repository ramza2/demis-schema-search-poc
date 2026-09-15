"""Catalog metadata compatibility for large cross-DB column lengths."""

from sqlalchemy import BigInteger

from app.db.catalog_bootstrap import _migrate_catalog_column_length_type
from app.models.catalog import CatalogColumn


class _ConnectionRecorder:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def execute(self, statement):  # noqa: ANN001
        self.sql.append(str(statement))


class _BeginContext:
    def __init__(self, conn: _ConnectionRecorder) -> None:
        self.conn = conn

    def __enter__(self) -> _ConnectionRecorder:
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False


class _EngineRecorder:
    def __init__(self) -> None:
        self.conn = _ConnectionRecorder()

    def begin(self) -> _BeginContext:
        return _BeginContext(self.conn)


def test_character_maximum_length_uses_bigint() -> None:
    column = CatalogColumn.__table__.c.character_maximum_length
    assert isinstance(column.type, BigInteger)


def test_existing_integer_length_column_is_migrated_to_bigint() -> None:
    engine = _EngineRecorder()

    _migrate_catalog_column_length_type(engine)  # type: ignore[arg-type]

    sql = "\n".join(engine.conn.sql)
    assert "character_maximum_length" in sql
    assert "data_type = 'integer'" in sql
    assert "TYPE BIGINT" in sql
