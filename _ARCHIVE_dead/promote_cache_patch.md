# Patch: wire schema_cache into promote_catalog.py

Goal: reflect schema metadata ONCE per run instead of per table. Each helper
gains a `if sc.ready(): <cache>` fast path and keeps its original live query as
the fallback, so nothing breaks if the cache wasn't primed (ad-hoc calls, tests).

Put `schema_cache.py` next to `promote_catalog.py`. Apply the 8 edits below.

────────────────────────────────────────────────────────────────────────────
EDIT 1 — add the import (top of file, just after the build_catalog_mirror import)
────────────────────────────────────────────────────────────────────────────
ADD:

    import schema_cache as sc

────────────────────────────────────────────────────────────────────────────
EDIT 2 — prime the cache once at the start of run_promote()
────────────────────────────────────────────────────────────────────────────
In run_promote(), make the FIRST line of the body:

    sc.prepare_schema(cur, DV_SCHEMA, CAT_SCHEMA)   # reflect schema ONCE
    if apply:
        _ensure_catalog_source(cur)
    ...

(prepare_schema runs 4 queries; everything below then reads from memory.)

────────────────────────────────────────────────────────────────────────────
EDIT 3 — object_exists()  (REPLACE the whole function)
────────────────────────────────────────────────────────────────────────────
def object_exists(cur, schema: str, table: str) -> bool:
    if sc.ready():
        return sc.table_exists(schema, table)
    cur.execute("SELECT OBJECT_ID(?)", f"{schema}.{table}")
    return cur.fetchone()[0] is not None

────────────────────────────────────────────────────────────────────────────
EDIT 4 — _computed_cols()  (REPLACE the whole function)
────────────────────────────────────────────────────────────────────────────
def _computed_cols(cur, dv_table: str) -> set:
    if sc.ready():
        return set(sc.computed_of(dv_table))
    cur.execute(
        "SELECT c.name FROM sys.columns c "
        "WHERE c.object_id = OBJECT_ID(?) AND c.is_computed = 1",
        f"{DV_SCHEMA}.{dv_table}")
    return {r[0].upper() for r in cur.fetchall()}

────────────────────────────────────────────────────────────────────────────
EDIT 5 — shared_columns()  (REPLACE only the two column-fetch lines)
────────────────────────────────────────────────────────────────────────────
FIND:
    dv_cols  = [c["COLUMN_NAME"] for c in fetch_columns(cur, DV_SCHEMA, dv_table)]
    cat_cols = {c["COLUMN_NAME"].upper()
                for c in fetch_columns(cur, CAT_SCHEMA, cat)}

REPLACE WITH:
    if sc.ready():
        dv_cols  = list(sc.cols_of(DV_SCHEMA, dv_table) or [])
        cat_cols = {c.upper() for c in (sc.cols_of(CAT_SCHEMA, cat) or [])}
    else:
        dv_cols  = [c["COLUMN_NAME"] for c in fetch_columns(cur, DV_SCHEMA, dv_table)]
        cat_cols = {c["COLUMN_NAME"].upper()
                    for c in fetch_columns(cur, CAT_SCHEMA, cat)}

(leave the rest of shared_columns — the computed lookup and the filter — as is.)

────────────────────────────────────────────────────────────────────────────
EDIT 6 — _reference_fk_predicates()  (REPLACE the cur.execute + fetch with this)
────────────────────────────────────────────────────────────────────────────
FIND the leading cur.execute("SELECT cpa.name, rt.name, cref.name ... ", DV_SCHEMA, dv_table)
and the subsequent `for local_col, ref_table, ref_col in cur.fetchall():`.

REPLACE the execute block so the loop iterates `fks` instead of cur.fetchall():

    if sc.ready():
        fks = sc.ref_fks_of(dv_table)
    else:
        cur.execute(
            "SELECT cpa.name, rt.name, cref.name "
            "FROM sys.foreign_keys fk "
            "JOIN sys.foreign_key_columns fkc "
            "       ON fkc.constraint_object_id = fk.object_id "
            "JOIN sys.tables  pt  ON pt.object_id = fk.parent_object_id "
            "JOIN sys.schemas ps  ON ps.schema_id = pt.schema_id "
            "JOIN sys.tables  rt  ON rt.object_id = fk.referenced_object_id "
            "JOIN sys.columns cpa ON cpa.object_id = fkc.parent_object_id "
            "                    AND cpa.column_id = fkc.parent_column_id "
            "JOIN sys.columns cref ON cref.object_id = fkc.referenced_object_id "
            "                     AND cref.column_id = fkc.referenced_column_id "
            "WHERE ps.name = ? AND pt.name = ? AND rt.name LIKE 'dv[_]r[_]%'",
            DV_SCHEMA, dv_table)
        fks = cur.fetchall()
    shared_lower = {s.lower() for s in shared}
    preds, cols = [], []
    for local_col, ref_table, ref_col in fks:
        if local_col.lower() not in shared_lower:
            continue
        preds.append(
            f" AND ({alias}.[{local_col}] IS NULL OR EXISTS "
            f"(SELECT 1 FROM {DV_SCHEMA}.[{ref_table}] r "
            f"WHERE r.[{ref_col}] = {alias}.[{local_col}]))")
        cols.append(local_col)
    return "".join(preds), cols

────────────────────────────────────────────────────────────────────────────
EDIT 7 — _referencing_children()  (REPLACE the whole function)
────────────────────────────────────────────────────────────────────────────
def _referencing_children(cur, dv_table: str) -> list:
    if sc.ready():
        return sc.children_of(dv_table)
    cur.execute(
        "SELECT DISTINCT OBJECT_NAME(fk.parent_object_id) "
        "FROM sys.foreign_keys fk "
        "WHERE fk.referenced_object_id = OBJECT_ID(?) "
        "AND fk.parent_object_id <> fk.referenced_object_id",
        f"{DV_SCHEMA}.{dv_table}")
    return [r[0] for r in cur.fetchall() if r[0]]

────────────────────────────────────────────────────────────────────────────
EDIT 8 — _has_inventory()  (REPLACE the whole function)
────────────────────────────────────────────────────────────────────────────
def _has_inventory(cur, table: str) -> bool:
    if sc.ready():
        return sc.has_inventory(table)
    cur.execute(
        "SELECT 1 FROM sys.columns "
        "WHERE object_id = OBJECT_ID(?) AND name = 'INVENTORY_ID'",
        f"{DV_SCHEMA}.{table}")
    return cur.fetchone() is not None

────────────────────────────────────────────────────────────────────────────
VERIFY
────────────────────────────────────────────────────────────────────────────
1. Behaviour unchanged: run the dry-run and confirm identical eligible counts:
       python promote_catalog.py --server localhost\SQLEXPRESS --database DataView_Demo
2. Speed: re-run the profiler per-table — each active table should drop from
   ~0.9 s to well under ~0.1 s:
       python pipeline_profiler.py --run-promote --per-table
   (clean any synthetic curves first: python seed_las_catalog.py --clean)
