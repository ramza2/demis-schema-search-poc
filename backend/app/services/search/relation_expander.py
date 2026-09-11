"""FK relation expansion via BFS over catalog_relation (no Graph DB).

Nodes are identified by (schema_name, table_name) or catalog_table.id —
never by bare table_name alone — so multi-schema catalogs do not collide.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import CatalogColumn, CatalogRelation, CatalogTable

TableKey = tuple[str, str]  # (schema_name, table_name)


@dataclass
class RelationHop:
    from_schema: str
    from_table: str
    to_schema: str
    to_table: str
    constraint_name: str
    direction: str  # outbound | inbound
    from_columns: list[str]
    to_columns: list[str]


@dataclass
class RelatedTableHit:
    table_name: str
    schema_name: str
    seed_schema: str
    seed_table: str
    hop_distance: int
    relation_path: list[RelationHop] = field(default_factory=list)
    match_type: str = "RELATED"

    @property
    def result_key(self) -> str:
        return (
            f"{self.seed_schema}.{self.seed_table}"
            f"->{self.schema_name}.{self.table_name}"
        )


def _normalize_seeds(
    seed_tables: list[TableKey] | None,
    seed_table_names: list[str] | None,
    *,
    default_schema: str = "public",
) -> list[TableKey]:
    seeds: list[TableKey] = []
    if seed_tables:
        for item in seed_tables:
            if isinstance(item, tuple) and len(item) == 2:
                schema, table = item
            else:
                continue
            if schema and table:
                seeds.append((str(schema), str(table)))
    if seed_table_names:
        for name in seed_table_names:
            if not name:
                continue
            if "." in name:
                schema, table = name.split(".", 1)
                seeds.append((schema, table))
            else:
                seeds.append((default_schema, name))
    return list(dict.fromkeys(seeds))


def expand_relations(
    session: Session,
    *,
    seed_tables: list[TableKey] | None = None,
    seed_table_names: list[str] | None = None,
    max_hops: int = 2,
    default_schema: str = "public",
) -> list[RelatedTableHit]:
    """Bidirectional BFS over FK edges. Cycle-safe via visited table ids."""
    max_hops = max(0, min(int(max_hops), 4))
    seeds = _normalize_seeds(seed_tables, seed_table_names, default_schema=default_schema)
    if max_hops == 0 or not seeds:
        return []

    tables = list(session.scalars(select(CatalogTable).where(CatalogTable.active.is_(True))).all())
    by_id = {t.id: t for t in tables}
    by_key: dict[TableKey, CatalogTable] = {(t.schema_name, t.table_name): t for t in tables}

    cols = list(session.scalars(select(CatalogColumn)).all())
    col_by_id = {c.id: c for c in cols}

    relations = list(
        session.scalars(select(CatalogRelation).where(CatalogRelation.active.is_(True))).all()
    )

    adjacency: dict[int, list[tuple[int, RelationHop]]] = defaultdict(list)
    for rel in relations:
        src = by_id.get(rel.source_table_id)
        tgt = by_id.get(rel.target_table_id)
        if src is None or tgt is None:
            continue
        rel_cols = sorted(rel.columns, key=lambda rc: rc.ordinal_position)
        src_names = [
            col_by_id[rc.source_column_id].column_name
            for rc in rel_cols
            if rc.source_column_id in col_by_id
        ]
        tgt_names = [
            col_by_id[rc.target_column_id].column_name
            for rc in rel_cols
            if rc.target_column_id in col_by_id
        ]
        outbound = RelationHop(
            from_schema=src.schema_name,
            from_table=src.table_name,
            to_schema=tgt.schema_name,
            to_table=tgt.table_name,
            constraint_name=rel.constraint_name,
            direction="outbound",
            from_columns=src_names,
            to_columns=tgt_names,
        )
        inbound = RelationHop(
            from_schema=tgt.schema_name,
            from_table=tgt.table_name,
            to_schema=src.schema_name,
            to_table=src.table_name,
            constraint_name=rel.constraint_name,
            direction="inbound",
            from_columns=tgt_names,
            to_columns=src_names,
        )
        adjacency[src.id].append((tgt.id, outbound))
        adjacency[tgt.id].append((src.id, inbound))

    results: dict[str, RelatedTableHit] = {}
    for seed_schema, seed_name in seeds:
        seed = by_key.get((seed_schema, seed_name))
        if seed is None:
            continue
        queue: deque[tuple[int, int, list[RelationHop]]] = deque([(seed.id, 0, [])])
        visited = {seed.id}
        while queue:
            node_id, dist, path = queue.popleft()
            if dist >= max_hops:
                continue
            for neighbor_id, hop in adjacency.get(node_id, []):
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                neighbor = by_id[neighbor_id]
                new_path = [*path, hop]
                new_dist = dist + 1
                key = (
                    f"{seed.schema_name}.{seed.table_name}"
                    f"->{neighbor.schema_name}.{neighbor.table_name}"
                )
                existing = results.get(key)
                if existing is None or new_dist < existing.hop_distance:
                    results[key] = RelatedTableHit(
                        table_name=neighbor.table_name,
                        schema_name=neighbor.schema_name,
                        seed_schema=seed.schema_name,
                        seed_table=seed.table_name,
                        hop_distance=new_dist,
                        relation_path=new_path,
                        match_type="RELATED",
                    )
                queue.append((neighbor_id, new_dist, new_path))

    return sorted(
        results.values(),
        key=lambda r: (r.hop_distance, r.seed_schema, r.seed_table, r.schema_name, r.table_name),
    )
