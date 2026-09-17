"""Persist successful-run schema snapshots and compare physical metadata changes."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.catalog_bootstrap import ensure_catalog_schema
from app.db.session import get_catalog_session_factory
from app.models.catalog import (
    CatalogAnalysisRun,
    CatalogColumn,
    CatalogIndex,
    CatalogIndexColumn,
    CatalogKeyConstraint,
    CatalogKeyConstraintColumn,
    CatalogRelation,
    CatalogRelationColumn,
    CatalogSource,
    CatalogTable,
)
from app.models.catalog_history import CatalogAnalysisSnapshot
from app.schemas.schema_diff_api import (
    DiffCount,
    SchemaDiffChange,
    SchemaDiffResponse,
    SchemaDiffSummary,
    SchemaRunListResponse,
    SchemaRunRef,
    SnapshotCaptureResponse,
)

SNAPSHOT_VERSION = "1.0"


def _run_schemas(run: CatalogAnalysisRun) -> list[str]:
    return [part.strip() for part in (run.target_schema or "").split(",") if part.strip()]


def _run_ref(run: CatalogAnalysisRun, snapshot: CatalogAnalysisSnapshot | None) -> SchemaRunRef:
    return SchemaRunRef(
        run_id=int(run.id),
        status=run.status,
        target_schema=run.target_schema,
        started_at=run.started_at,
        finished_at=run.finished_at,
        table_count=run.table_count or 0,
        column_count=run.column_count or 0,
        relation_count=run.relation_count or 0,
        index_count=run.index_count or 0,
        schema_fingerprint=run.schema_fingerprint,
        snapshot_available=snapshot is not None,
        snapshot_created_at=snapshot.created_at if snapshot else None,
        capture_mode=snapshot.capture_mode if snapshot else None,
    )


def _table_key(item: dict[str, Any]) -> str:
    return f"{item.get('schema', '')}.{item.get('name', '')}"


def _column_key(item: dict[str, Any]) -> str:
    return f"{item.get('schema', '')}.{item.get('table', '')}.{item.get('name', '')}"


def _constraint_key(item: dict[str, Any]) -> str:
    return f"{item.get('schema', '')}.{item.get('table', '')}.{item.get('name', '')}"


def _fk_key(item: dict[str, Any]) -> str:
    return f"{item.get('source_schema', '')}.{item.get('source_table', '')}.{item.get('name', '')}"


def _index_key(item: dict[str, Any]) -> str:
    return f"{item.get('schema', '')}.{item.get('table', '')}.{item.get('name', '')}"


_ENTITY_SPECS: tuple[
    tuple[str, str, Callable[[dict[str, Any]], str], tuple[str, ...]], ...
] = (
    ("tables", "TABLE", _table_key, ("schema", "name")),
    ("columns", "COLUMN", _column_key, ("schema", "table", "name")),
    (
        "key_constraints",
        "KEY_CONSTRAINT",
        _constraint_key,
        ("schema", "table", "name"),
    ),
    (
        "foreign_keys",
        "FOREIGN_KEY",
        _fk_key,
        ("source_schema", "source_table", "name"),
    ),
    ("indexes", "INDEX", _index_key, ("schema", "table", "name")),
)


def compare_snapshot_payloads(
    base_payload: dict[str, Any], target_payload: dict[str, Any]
) -> tuple[SchemaDiffSummary, list[SchemaDiffChange]]:
    """Pure deterministic comparison used by API and focused tests."""

    changes: list[SchemaDiffChange] = []
    counts: dict[str, DiffCount] = {}

    for payload_key, object_type, key_func, identity_fields in _ENTITY_SPECS:
        base_items = {
            key_func(item): item for item in (base_payload.get(payload_key) or [])
        }
        target_items = {
            key_func(item): item for item in (target_payload.get(payload_key) or [])
        }
        count = DiffCount()

        for object_key in sorted(target_items.keys() - base_items.keys()):
            count.added += 1
            changes.append(
                SchemaDiffChange(
                    object_type=object_type,
                    change_type="ADDED",
                    object_key=object_key,
                    after=target_items[object_key],
                )
            )

        for object_key in sorted(base_items.keys() - target_items.keys()):
            count.removed += 1
            changes.append(
                SchemaDiffChange(
                    object_type=object_type,
                    change_type="REMOVED",
                    object_key=object_key,
                    before=base_items[object_key],
                )
            )

        for object_key in sorted(base_items.keys() & target_items.keys()):
            before = base_items[object_key]
            after = target_items[object_key]
            fields = sorted(
                field
                for field in (set(before) | set(after)) - set(identity_fields)
                if before.get(field) != after.get(field)
            )
            if fields:
                count.changed += 1
                changes.append(
                    SchemaDiffChange(
                        object_type=object_type,
                        change_type="CHANGED",
                        object_key=object_key,
                        changed_fields=fields,
                        before=before,
                        after=after,
                    )
                )
        counts[payload_key] = count

    total = sum(item.total for item in counts.values())
    summary = SchemaDiffSummary(
        tables=counts["tables"],
        columns=counts["columns"],
        key_constraints=counts["key_constraints"],
        foreign_keys=counts["foreign_keys"],
        indexes=counts["indexes"],
        total_changes=total,
    )
    return summary, changes


class SchemaDiffService:
    """Snapshot and compare source-scoped successful schema analysis runs."""

    def __init__(self) -> None:
        ensure_catalog_schema()
        self._factory = get_catalog_session_factory()

    def _session(self) -> Session:
        return self._factory()

    @staticmethod
    def _latest_success(session: Session, source_id: int) -> CatalogAnalysisRun | None:
        return session.scalar(
            select(CatalogAnalysisRun)
            .where(
                CatalogAnalysisRun.source_id == source_id,
                CatalogAnalysisRun.status == "SUCCESS",
            )
            .order_by(CatalogAnalysisRun.id.desc())
            .limit(1)
        )

    def list_runs(self, target_id: int) -> SchemaRunListResponse:
        session = self._session()
        try:
            source = session.get(CatalogSource, target_id)
            if source is None:
                raise LookupError(f"target not found: {target_id}")
            rows = session.execute(
                select(CatalogAnalysisRun, CatalogAnalysisSnapshot)
                .outerjoin(
                    CatalogAnalysisSnapshot,
                    CatalogAnalysisSnapshot.run_id == CatalogAnalysisRun.id,
                )
                .where(
                    CatalogAnalysisRun.source_id == target_id,
                    CatalogAnalysisRun.status == "SUCCESS",
                )
                .order_by(CatalogAnalysisRun.id.desc())
            ).all()
            return SchemaRunListResponse(
                source_id=target_id,
                source_name=source.source_name,
                runs=[_run_ref(run, snapshot) for run, snapshot in rows],
            )
        finally:
            session.close()

    def capture_latest_baseline(self, target_id: int) -> SnapshotCaptureResponse:
        """Backfill only the latest SUCCESS run because Catalog stores current state."""
        session = self._session()
        try:
            source = session.get(CatalogSource, target_id)
            if source is None:
                raise LookupError(f"target not found: {target_id}")
            run = self._latest_success(session, target_id)
            if run is None:
                raise ValueError("no successful analysis run exists for this Target")
            return self._capture_current(
                session,
                source=source,
                run=run,
                capture_mode="CURRENT_CATALOG_BASELINE",
                require_latest=True,
            )
        finally:
            session.close()

    def capture_run(
        self,
        run_id: int,
        *,
        expected_source_id: int | None = None,
        capture_mode: str = "ANALYSIS_API",
    ) -> SnapshotCaptureResponse:
        """Capture a just-completed SUCCESS run if it is still the latest source run."""
        session = self._session()
        try:
            run = session.get(CatalogAnalysisRun, run_id)
            if run is None:
                raise LookupError(f"analysis run not found: {run_id}")
            if expected_source_id is not None and int(run.source_id) != int(expected_source_id):
                raise ValueError("analysis run does not belong to the expected Target")
            source = session.get(CatalogSource, run.source_id)
            if source is None:
                raise LookupError(f"target not found: {run.source_id}")
            return self._capture_current(
                session,
                source=source,
                run=run,
                capture_mode=capture_mode,
                require_latest=True,
            )
        finally:
            session.close()

    def _capture_current(
        self,
        session: Session,
        *,
        source: CatalogSource,
        run: CatalogAnalysisRun,
        capture_mode: str,
        require_latest: bool,
    ) -> SnapshotCaptureResponse:
        if run.status != "SUCCESS":
            raise ValueError(f"only SUCCESS runs can be snapshotted: run_id={run.id}")

        existing = session.scalar(
            select(CatalogAnalysisSnapshot).where(
                CatalogAnalysisSnapshot.run_id == run.id
            )
        )
        if existing is not None:
            return SnapshotCaptureResponse(
                source_id=int(source.id),
                source_name=source.source_name,
                run_id=int(run.id),
                created=False,
                capture_mode=existing.capture_mode,
                snapshot_version=existing.snapshot_version,
                created_at=existing.created_at,
            )

        if require_latest:
            latest = self._latest_success(session, int(source.id))
            if latest is None or int(latest.id) != int(run.id):
                raise ValueError(
                    "current Catalog can only be captured for the latest SUCCESS run; "
                    "older runs cannot be reconstructed safely"
                )

        payload = self._build_current_payload(session, run)
        snapshot = CatalogAnalysisSnapshot(
            source_id=int(source.id),
            run_id=int(run.id),
            snapshot_version=SNAPSHOT_VERSION,
            capture_mode=capture_mode,
            payload=payload,
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        return SnapshotCaptureResponse(
            source_id=int(source.id),
            source_name=source.source_name,
            run_id=int(run.id),
            created=True,
            capture_mode=snapshot.capture_mode,
            snapshot_version=snapshot.snapshot_version,
            created_at=snapshot.created_at,
        )

    @staticmethod
    def _build_current_payload(session: Session, run: CatalogAnalysisRun) -> dict[str, Any]:
        schemas = _run_schemas(run)
        if not schemas:
            raise ValueError(f"analysis run has no target schema: run_id={run.id}")

        tables = list(
            session.scalars(
                select(CatalogTable)
                .where(
                    CatalogTable.source_id == run.source_id,
                    CatalogTable.schema_name.in_(schemas),
                    CatalogTable.active.is_(True),
                )
                .order_by(CatalogTable.schema_name, CatalogTable.table_name)
            ).all()
        )
        table_by_id = {int(table.id): table for table in tables}
        table_ids = list(table_by_id)

        columns: list[CatalogColumn] = []
        if table_ids:
            columns = list(
                session.scalars(
                    select(CatalogColumn)
                    .where(
                        CatalogColumn.table_id.in_(table_ids),
                        CatalogColumn.active.is_(True),
                    )
                    .order_by(CatalogColumn.table_id, CatalogColumn.ordinal_position)
                ).all()
            )
        column_by_id = {int(column.id): column for column in columns}

        key_constraints: list[CatalogKeyConstraint] = []
        indexes: list[CatalogIndex] = []
        relations: list[CatalogRelation] = []
        if table_ids:
            key_constraints = list(
                session.scalars(
                    select(CatalogKeyConstraint).where(
                        CatalogKeyConstraint.table_id.in_(table_ids),
                        CatalogKeyConstraint.active.is_(True),
                    )
                ).all()
            )
            indexes = list(
                session.scalars(
                    select(CatalogIndex).where(
                        CatalogIndex.table_id.in_(table_ids),
                        CatalogIndex.active.is_(True),
                    )
                ).all()
            )
            relations = list(
                session.scalars(
                    select(CatalogRelation).where(
                        CatalogRelation.source_id == run.source_id,
                        CatalogRelation.source_table_id.in_(table_ids),
                        CatalogRelation.active.is_(True),
                    )
                ).all()
            )

        key_cols: dict[int, list[CatalogKeyConstraintColumn]] = defaultdict(list)
        key_ids = [int(item.id) for item in key_constraints]
        if key_ids:
            rows = session.scalars(
                select(CatalogKeyConstraintColumn)
                .where(CatalogKeyConstraintColumn.constraint_id.in_(key_ids))
                .order_by(
                    CatalogKeyConstraintColumn.constraint_id,
                    CatalogKeyConstraintColumn.ordinal_position,
                )
            ).all()
            for row in rows:
                key_cols[int(row.constraint_id)].append(row)

        index_cols: dict[int, list[CatalogIndexColumn]] = defaultdict(list)
        index_ids = [int(item.id) for item in indexes]
        if index_ids:
            rows = session.scalars(
                select(CatalogIndexColumn)
                .where(CatalogIndexColumn.index_id.in_(index_ids))
                .order_by(
                    CatalogIndexColumn.index_id,
                    CatalogIndexColumn.ordinal_position,
                )
            ).all()
            for row in rows:
                index_cols[int(row.index_id)].append(row)

        relation_cols: dict[int, list[CatalogRelationColumn]] = defaultdict(list)
        relation_ids = [int(item.id) for item in relations]
        relation_column_ids: set[int] = set()
        if relation_ids:
            rows = session.scalars(
                select(CatalogRelationColumn)
                .where(CatalogRelationColumn.relation_id.in_(relation_ids))
                .order_by(
                    CatalogRelationColumn.relation_id,
                    CatalogRelationColumn.ordinal_position,
                )
            ).all()
            for row in rows:
                relation_cols[int(row.relation_id)].append(row)
                relation_column_ids.add(int(row.source_column_id))
                relation_column_ids.add(int(row.target_column_id))

        missing_column_ids = relation_column_ids - set(column_by_id)
        if missing_column_ids:
            for column in session.scalars(
                select(CatalogColumn).where(CatalogColumn.id.in_(missing_column_ids))
            ).all():
                column_by_id[int(column.id)] = column

        related_table_ids = {
            int(item.target_table_id) for item in relations if int(item.target_table_id) not in table_by_id
        }
        if related_table_ids:
            for table in session.scalars(
                select(CatalogTable).where(CatalogTable.id.in_(related_table_ids))
            ).all():
                table_by_id[int(table.id)] = table

        payload_tables = [
            {
                "schema": table.schema_name,
                "name": table.table_name,
                "table_type": table.table_type,
                "comment": table.table_comment,
            }
            for table in tables
        ]
        payload_columns = []
        for column in columns:
            table = table_by_id[int(column.table_id)]
            payload_columns.append(
                {
                    "schema": table.schema_name,
                    "table": table.table_name,
                    "name": column.column_name,
                    "ordinal": column.ordinal_position,
                    "data_type": column.data_type,
                    "char_length": column.character_maximum_length,
                    "numeric_precision": column.numeric_precision,
                    "numeric_scale": column.numeric_scale,
                    "nullable": column.is_nullable,
                    "default": column.default_value,
                    "comment": column.column_comment,
                }
            )

        payload_keys = []
        for constraint in sorted(
            key_constraints,
            key=lambda item: (
                table_by_id[int(item.table_id)].schema_name,
                table_by_id[int(item.table_id)].table_name,
                item.constraint_name,
            ),
        ):
            table = table_by_id[int(constraint.table_id)]
            names = []
            for ref in key_cols[int(constraint.id)]:
                column = column_by_id.get(int(ref.column_id))
                if column is not None:
                    names.append(column.column_name)
            payload_keys.append(
                {
                    "schema": table.schema_name,
                    "table": table.table_name,
                    "name": constraint.constraint_name,
                    "constraint_type": constraint.constraint_type,
                    "columns": names,
                }
            )

        payload_fks = []
        for relation in sorted(
            relations,
            key=lambda item: (
                table_by_id[int(item.source_table_id)].schema_name,
                table_by_id[int(item.source_table_id)].table_name,
                item.constraint_name,
            ),
        ):
            source_table = table_by_id[int(relation.source_table_id)]
            target_table = table_by_id.get(int(relation.target_table_id))
            mappings = []
            for ref in relation_cols[int(relation.id)]:
                source_column = column_by_id.get(int(ref.source_column_id))
                target_column = column_by_id.get(int(ref.target_column_id))
                mappings.append(
                    {
                        "source": source_column.column_name if source_column else str(ref.source_column_id),
                        "target": target_column.column_name if target_column else str(ref.target_column_id),
                    }
                )
            payload_fks.append(
                {
                    "source_schema": source_table.schema_name,
                    "source_table": source_table.table_name,
                    "name": relation.constraint_name,
                    "target_schema": target_table.schema_name if target_table else "",
                    "target_table": target_table.table_name if target_table else "",
                    "mappings": mappings,
                }
            )

        payload_indexes = []
        for index in sorted(
            indexes,
            key=lambda item: (
                table_by_id[int(item.table_id)].schema_name,
                table_by_id[int(item.table_id)].table_name,
                item.index_name,
            ),
        ):
            table = table_by_id[int(index.table_id)]
            payload_indexes.append(
                {
                    "schema": table.schema_name,
                    "table": table.table_name,
                    "name": index.index_name,
                    "unique": index.is_unique,
                    "method": index.index_method,
                    "definition": index.index_definition,
                    "columns": [ref.column_name for ref in index_cols[int(index.id)]],
                }
            )

        return {
            "snapshot_version": SNAPSHOT_VERSION,
            "run_id": int(run.id),
            "source_id": int(run.source_id),
            "target_schema": run.target_schema,
            "schema_fingerprint": run.schema_fingerprint,
            "tables": payload_tables,
            "columns": payload_columns,
            "key_constraints": payload_keys,
            "foreign_keys": payload_fks,
            "indexes": payload_indexes,
        }

    def compare(self, target_id: int, base_run_id: int, target_run_id: int) -> SchemaDiffResponse:
        if base_run_id == target_run_id:
            raise ValueError("base_run_id and target_run_id must be different")

        session = self._session()
        try:
            source = session.get(CatalogSource, target_id)
            if source is None:
                raise LookupError(f"target not found: {target_id}")

            base_run = session.get(CatalogAnalysisRun, base_run_id)
            target_run = session.get(CatalogAnalysisRun, target_run_id)
            if base_run is None:
                raise LookupError(f"analysis run not found: {base_run_id}")
            if target_run is None:
                raise LookupError(f"analysis run not found: {target_run_id}")
            if int(base_run.source_id) != target_id or int(target_run.source_id) != target_id:
                raise ValueError("both runs must belong to the selected Target")
            if base_run.status != "SUCCESS" or target_run.status != "SUCCESS":
                raise ValueError("only SUCCESS runs can be compared")

            base_snapshot = session.scalar(
                select(CatalogAnalysisSnapshot).where(
                    CatalogAnalysisSnapshot.run_id == base_run_id
                )
            )
            target_snapshot = session.scalar(
                select(CatalogAnalysisSnapshot).where(
                    CatalogAnalysisSnapshot.run_id == target_run_id
                )
            )
            if base_snapshot is None or target_snapshot is None:
                missing = []
                if base_snapshot is None:
                    missing.append(str(base_run_id))
                if target_snapshot is None:
                    missing.append(str(target_run_id))
                raise ValueError(
                    "schema snapshot is unavailable for run(s): " + ", ".join(missing)
                )

            summary, changes = compare_snapshot_payloads(
                base_snapshot.payload,
                target_snapshot.payload,
            )
            return SchemaDiffResponse(
                source_id=target_id,
                source_name=source.source_name,
                base_run=_run_ref(base_run, base_snapshot),
                target_run=_run_ref(target_run, target_snapshot),
                identical=summary.total_changes == 0,
                summary=summary,
                changes=changes,
            )
        finally:
            session.close()
