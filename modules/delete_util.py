"""
delete_util.py  —  PPDM Loader · Cascade Delete Utility
=========================================================
Introspects sys.foreign_keys to build the correct deletion
order, then executes DELETE statements inside a single
transaction.

Supports:
  - Full wipe of dbo.well and all FK-dependent child tables
  - Dry-run mode: show the plan without executing
  - Row count preview per table before committing

Test:
    python delete_util.py
"""

from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class DeleteTablePlan:
    """One table in the cascade delete plan."""
    schema:       str
    table:        str
    depth:        int          # deletion order (higher = delete first)
    row_count:    int = -1     # -1 = not yet counted
    fk_cols:      list[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"[{self.schema}].[{self.table}]"

    @property
    def delete_sql(self) -> str:
        return f"DELETE FROM {self.full_name};"


@dataclass
class DeletePlan:
    """Full ordered plan for a cascade delete."""
    root_table:  str
    root_schema: str
    tables:      list[DeleteTablePlan]   # ordered: deepest first, root last

    @property
    def total_rows(self) -> int:
        return sum(t.row_count for t in self.tables if t.row_count >= 0)

    @property
    def table_names(self) -> list[str]:
        return [t.full_name for t in self.tables]


@dataclass
class DeleteResult:
    ok:            bool
    message:       str
    rows_deleted:  dict[str, int] = field(default_factory=dict)  # table → rows
    total_deleted: int = 0
    dry_run:       bool = False


# ═══════════════════════════════════════════════════════════════════════
# PLAN BUILDER — introspects sys.foreign_keys recursively
# ═══════════════════════════════════════════════════════════════════════

def build_delete_plan(
    engine,
    root_table:  str = "well",
    root_schema: str = "dbo",
) -> DeletePlan:
    """
    Walk sys.foreign_keys recursively to find every table that
    directly or indirectly FK-references root_table.

    Returns a DeletePlan with tables ordered deepest-first so
    child rows are deleted before parent rows.
    """
    from sqlalchemy import text

    discovery_sql = """
    ;WITH fk_deps AS (
        SELECT
            cs.name   AS child_schema,
            ct.name   AS child_table,
            cc.name   AS fk_col,
            1         AS depth
        FROM sys.foreign_keys        fk
        JOIN sys.foreign_key_columns fkc
             ON  fkc.constraint_object_id = fk.object_id
             AND fkc.constraint_column_id = 1
        JOIN sys.tables  ct  ON ct.object_id  = fk.parent_object_id
        JOIN sys.schemas cs  ON cs.schema_id  = ct.schema_id
        JOIN sys.tables  pt  ON pt.object_id  = fk.referenced_object_id
        JOIN sys.schemas ps  ON ps.schema_id  = pt.schema_id
        JOIN sys.columns cc  ON cc.object_id  = fk.parent_object_id
                            AND cc.column_id  = fkc.parent_column_id
        WHERE pt.name = :root_table AND ps.name = :root_schema

        UNION ALL

        SELECT
            cs.name, ct.name, cc.name,
            fd.depth + 1
        FROM sys.foreign_keys        fk
        JOIN sys.foreign_key_columns fkc
             ON  fkc.constraint_object_id = fk.object_id
             AND fkc.constraint_column_id = 1
        JOIN sys.tables  ct  ON ct.object_id  = fk.parent_object_id
        JOIN sys.schemas cs  ON cs.schema_id  = ct.schema_id
        JOIN sys.tables  pt  ON pt.object_id  = fk.referenced_object_id
        JOIN sys.schemas ps  ON ps.schema_id  = pt.schema_id
        JOIN sys.columns cc  ON cc.object_id  = fk.parent_object_id
                            AND cc.column_id  = fkc.parent_column_id
        JOIN fk_deps fd      ON fd.child_schema = ps.name
                            AND fd.child_table  = pt.name
        WHERE fd.depth < 15
    )
    SELECT
        child_schema,
        child_table,
        MAX(depth)              AS max_depth,
        STRING_AGG(fk_col, ',') AS fk_cols
    FROM fk_deps
    GROUP BY child_schema, child_table
    ORDER BY max_depth DESC, child_table
    """

    with engine.connect() as con:
        rows = con.execute(
            text(discovery_sql),
            {"root_table": root_table, "root_schema": root_schema}
        ).fetchall()

    # Build plan — child tables first
    tables: list[DeleteTablePlan] = []
    for row in rows:
        fk_cols = [c.strip() for c in (row[3] or "").split(",") if c.strip()]
        tables.append(DeleteTablePlan(
            schema   = row[0],
            table    = row[1],
            depth    = row[2],
            fk_cols  = fk_cols,
        ))

    # Append root table last (depth 0)
    tables.append(DeleteTablePlan(
        schema = root_schema,
        table  = root_table,
        depth  = 0,
    ))

    return DeletePlan(
        root_table  = root_table,
        root_schema = root_schema,
        tables      = tables,
    )


# ═══════════════════════════════════════════════════════════════════════
# ROW COUNT PREVIEW
# ═══════════════════════════════════════════════════════════════════════

def count_rows(engine, plan: DeletePlan) -> DeletePlan:
    """
    Populate row_count for every table in the plan.
    Uses fast sys.partitions estimate — accurate for most cases.
    """
    from sqlalchemy import text

    count_sql = """
    SELECT
        s.name AS schema_name,
        t.name AS table_name,
        SUM(p.rows) AS row_count
    FROM sys.tables     t
    JOIN sys.schemas    s  ON s.schema_id  = t.schema_id
    JOIN sys.partitions p  ON p.object_id  = t.object_id
                          AND p.index_id   IN (0, 1)   -- heap or clustered
    WHERE t.name   IN :tables
      AND s.name   IN :schemas
    GROUP BY s.name, t.name
    """

    table_names  = [tp.table  for tp in plan.tables]
    schema_names = list({tp.schema for tp in plan.tables})

    # Build IN clause manually (avoid bind param issues with tuples)
    tbl_in  = ", ".join(f"'{t}'" for t in table_names)
    sch_in  = ", ".join(f"'{s}'" for s in schema_names)

    sql = f"""
    SELECT s.name, t.name, SUM(p.rows)
    FROM sys.tables     t
    JOIN sys.schemas    s  ON s.schema_id = t.schema_id
    JOIN sys.partitions p  ON p.object_id = t.object_id
                          AND p.index_id  IN (0, 1)
    WHERE t.name IN ({tbl_in}) AND s.name IN ({sch_in})
    GROUP BY s.name, t.name
    """

    counts: dict[tuple, int] = {}
    with engine.connect() as con:
        for row in con.execute(text(sql)).fetchall():
            counts[(row[0].lower(), row[1].lower())] = int(row[2] or 0)

    for tp in plan.tables:
        tp.row_count = counts.get((tp.schema.lower(), tp.table.lower()), 0)

    return plan


# ═══════════════════════════════════════════════════════════════════════
# EXECUTE DELETE
# ═══════════════════════════════════════════════════════════════════════

def execute_delete(
    engine,
    plan:    DeletePlan,
    dry_run: bool = False,
) -> DeleteResult:
    """
    Execute the cascade delete inside a single transaction.

    dry_run=True: build and return the plan without executing any SQL.

    Tables are deleted in plan order (deepest child first, root last).
    Any error triggers a full rollback.
    """
    if dry_run:
        return DeleteResult(
            ok=True,
            message=f"Dry run — {len(plan.tables)} table(s) would be deleted. "
                    f"Total rows: {plan.total_rows:,}",
            rows_deleted={t.full_name: t.row_count for t in plan.tables},
            total_deleted=plan.total_rows,
            dry_run=True,
        )

    from sqlalchemy import text

    rows_deleted: dict[str, int] = {}
    total = 0

    try:
        with engine.begin() as con:   # single transaction
            for tp in plan.tables:
                result = con.execute(text(tp.delete_sql))
                n = result.rowcount if result.rowcount >= 0 else 0
                rows_deleted[tp.full_name] = n
                total += n

        return DeleteResult(
            ok=True,
            message=f"Cascade delete complete — {total:,} total row(s) deleted "
                    f"across {len(plan.tables)} table(s).",
            rows_deleted=rows_deleted,
            total_deleted=total,
            dry_run=False,
        )

    except Exception as exc:
        return DeleteResult(
            ok=False,
            message=f"Delete failed (transaction rolled back): {exc}",
            rows_deleted=rows_deleted,
            dry_run=False,
        )


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("PPDM Loader — delete_util.py — Self Test")
    print("=" * 60)

    # Test 1: DeleteTablePlan
    print("\n[TEST 1] DeleteTablePlan")
    tp = DeleteTablePlan(schema="dbo", table="well_alias", depth=2,
                         fk_cols=["UWI"])
    assert tp.full_name  == "[dbo].[well_alias]"
    assert tp.delete_sql == "DELETE FROM [dbo].[well_alias];"
    print(f"  ✓  full_name:  {tp.full_name}")
    print(f"  ✓  delete_sql: {tp.delete_sql}")

    # Test 2: DeletePlan ordering
    print("\n[TEST 2] DeletePlan total rows")
    plan = DeletePlan(
        root_table="well", root_schema="dbo",
        tables=[
            DeleteTablePlan("dbo", "well_alias",   2, row_count=10),
            DeleteTablePlan("dbo", "well_station",  1, row_count=50),
            DeleteTablePlan("dbo", "well",          0, row_count=5),
        ]
    )
    assert plan.total_rows == 65
    assert plan.table_names == [
        "[dbo].[well_alias]", "[dbo].[well_station]", "[dbo].[well]"
    ]
    print(f"  ✓  total_rows: {plan.total_rows}")
    print(f"  ✓  tables:     {plan.table_names}")

    # Test 3: Dry run
    print("\n[TEST 3] Dry run (no engine)")
    result = execute_delete(engine=None, plan=plan, dry_run=True)
    assert result.ok
    assert result.dry_run
    assert result.total_deleted == 65
    print(f"  ✓  dry_run:        {result.dry_run}")
    print(f"  ✓  total_deleted:  {result.total_deleted}")
    print(f"  ✓  message:        {result.message}")

    # Test 4: DeleteResult rows_deleted dict
    print("\n[TEST 4] DeleteResult structure")
    assert "[dbo].[well_alias]"   in result.rows_deleted
    assert "[dbo].[well_station]" in result.rows_deleted
    assert "[dbo].[well]"         in result.rows_deleted
    print(f"  ✓  rows_deleted: {result.rows_deleted}")

    print("\n" + "=" * 60)
    print("All tests passed ✓")
    print("=" * 60)
