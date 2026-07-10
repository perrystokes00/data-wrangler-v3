"""
schema_introspect.py
=====================
Live introspection of the DataView SQL Server schema, shared by the docs
generator (gen_schema_docs.py) and the in-app overview page
(page_schema_overview.py).

Pulls tables / columns / primary keys / declared foreign keys / fast row
counts from the system catalog, assigns every table to a subject area, and
infers relationship edges where hard FK constraints don't exist (the
federation is built on logical UWI identity, so declared FKs are sparse).

Nothing here scans table data — row counts come from
sys.dm_db_partition_stats, so it stays fast even with 77.9M production rows.
"""
from __future__ import annotations

import re
from sqlalchemy import text


# ─────────────────────────────────────────────────────────────────────────
# Subject areas
# ─────────────────────────────────────────────────────────────────────────
# Display order, label, icon, accent colour, and a one-line description.
AREA_ORDER = [
    "wells", "completions", "production", "directional",
    "formation", "reference", "spatial", "documents", "other",
]

AREA_META = {
    "wells": {
        "label": "Wells & Wellbores", "icon": "🛢", "color": "#1D9E75",
        "desc": "Core well identity plus the per-source federation extension "
                "tables. Everything in the model hangs off the UWI.",
    },
    "completions": {
        "label": "Completions & Stimulation", "icon": "🔧", "color": "#378ADD",
        "desc": "Completion intervals, perforations, and stimulation / frac "
                "treatments tied back to the well.",
    },
    "production": {
        "label": "Production & Volumes", "icon": "📈", "color": "#EF9F27",
        "desc": "Monthly oil / gas / water volumes joined through the well and "
                "completion.",
    },
    "directional": {
        "label": "Directional Surveys", "icon": "🧭", "color": "#B77FDD",
        "desc": "Deviation survey stations — measured depth, inclination, "
                "azimuth, and TVD per wellbore.",
    },
    "formation": {
        "label": "Formations, Tops & Tests", "icon": "🪨", "color": "#C96A4B",
        "desc": "Formation tops / markers, drill-stem test intervals, and core "
                "data.",
    },
    "reference": {
        "label": "Reference & Lookups", "icon": "📚", "color": "#5B8DA0",
        "desc": "Business associates, fields, units, and PPDM reference / "
                "standard values that the data tables point at.",
    },
    "spatial": {
        "label": "Spatial & Political", "icon": "🗺", "color": "#7FA653",
        "desc": "County / state / PLSS / census boundaries, basins and plays, "
                "and BOEM lease blocks.",
    },
    "documents": {
        "label": "Documents & Catalog", "icon": "📁", "color": "#9AA0A6",
        "desc": "File inventory, catalog scoring, scout tickets, and the LAS / "
                "PDF source assets.",
    },
    "other": {
        "label": "Other", "icon": "📦", "color": "#888780",
        "desc": "Tables not yet classified into a subject area — adjust the "
                "rules or supply an overrides file to reclassify.",
    },
}

# First match wins. Ordered most-specific → most-general so that, e.g.,
# dv_well_completion lands in 'completions', not 'wells'. Substrings are
# matched against the lower-cased table name.
AREA_RULES = [
    ("completions", ["completion", "perforation", "perf", "frac",
                     "stimulation", "stim", "treatment"]),
    ("production",  ["production", "prod", "volume", "disposition",
                     "allowable"]),
    ("directional", ["dir_srvy", "directional", "deviation", "survey",
                     "_srvy", "wellpath", "wellbore_path"]),
    ("formation",   ["formation", "strat", "_top", "tops", "marker",
                     "dst", "drillstem", "core", "pick", "zone"]),
    ("spatial",     ["county", "counties", "state", "province", "plss",
                     "township", "section", "census", "tiger", "gadm",
                     "boem", "lease", "block", "protraction", "political",
                     "basin", "play", "geom", "spatial", "boundary",
                     "region", "quadrangle"]),
    ("documents",   ["file", "document", "doc_", "catalog", "inventory",
                     "scout", "ticket", "las_", "attachment", "image",
                     "report"]),
    ("reference",   ["business_associate", "_ba_", "field", "operator",
                     "company", "ref_", "_ref", "lookup", "unit", "uom",
                     "code", "standard", "datum", "r_"]),
    ("wells",       ["well", "wellbore", "uwi", "api"]),
]


def assign_area(table_name: str, overrides: dict | None = None) -> str:
    """Return the subject-area key for a table name."""
    if overrides and table_name in overrides:
        return overrides[table_name]
    low = table_name.lower()
    for area, needles in AREA_RULES:
        if any(n in low for n in needles):
            return area
    return "other"


# ─────────────────────────────────────────────────────────────────────────
# Connection helper (standalone script path)
# ─────────────────────────────────────────────────────────────────────────
def make_engine(server: str, database: str, driver: str | None = None):
    """Build a SQLAlchemy engine for SQL Server using Windows auth.

    The app passes its own engine to build_model(); this is only for the
    standalone generator.
    """
    import urllib.parse
    import pyodbc
    from sqlalchemy import create_engine

    if not driver:
        prefer = [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "ODBC Driver 13 for SQL Server",
            "SQL Server Native Client 11.0",
            "ODBC Driver 11 for SQL Server",
        ]
        avail = set(pyodbc.drivers())
        driver = next((d for d in prefer if d in avail), None)
        if not driver:
            raise RuntimeError(
                "No suitable SQL Server ODBC driver found. "
                f"Installed drivers: {sorted(avail)}")

    odbc = (f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};"
            "Trusted_Connection=yes;TrustServerCertificate=yes")
    url = "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(odbc)
    return create_engine(url)


# ─────────────────────────────────────────────────────────────────────────
# Catalog queries
# ─────────────────────────────────────────────────────────────────────────
_Q_TABLES = """
    SELECT t.object_id, t.name AS table_name
    FROM sys.tables t
    JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE s.name = :schema
    ORDER BY t.name
"""

_Q_COLUMNS = """
    SELECT c.object_id, c.column_id, c.name AS column_name,
           ty.name AS data_type, c.max_length, c.precision,
           c.scale, c.is_nullable
    FROM sys.columns c
    JOIN sys.types ty ON ty.user_type_id = c.user_type_id
    JOIN sys.tables t ON t.object_id = c.object_id
    JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE s.name = :schema
    ORDER BY c.object_id, c.column_id
"""

_Q_PKS = """
    SELECT t.name AS table_name, c.name AS column_name
    FROM sys.indexes i
    JOIN sys.index_columns ic
         ON ic.object_id = i.object_id AND ic.index_id = i.index_id
    JOIN sys.columns c
         ON c.object_id = ic.object_id AND c.column_id = ic.column_id
    JOIN sys.tables t ON t.object_id = i.object_id
    JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE i.is_primary_key = 1 AND s.name = :schema
"""

# In sys.foreign_keys the "parent" table is the *referencing* (child) table
# and "referenced" is the *parent* table it points at.
_Q_FKS = """
    SELECT tp.name AS child_table,  cp.name AS child_col,
           tr.name AS parent_table, cr.name AS parent_col
    FROM sys.foreign_keys fk
    JOIN sys.foreign_key_columns fkc
         ON fkc.constraint_object_id = fk.object_id
    JOIN sys.tables  tp ON tp.object_id = fkc.parent_object_id
    JOIN sys.columns cp ON cp.object_id = fkc.parent_object_id
                       AND cp.column_id = fkc.parent_column_id
    JOIN sys.tables  tr ON tr.object_id = fkc.referenced_object_id
    JOIN sys.columns cr ON cr.object_id = fkc.referenced_object_id
                       AND cr.column_id = fkc.referenced_column_id
    JOIN sys.schemas s ON s.schema_id = tp.schema_id
    WHERE s.name = :schema
"""

_Q_ROWCOUNTS = """
    SELECT t.name AS table_name, SUM(ps.row_count) AS row_count
    FROM sys.dm_db_partition_stats ps
    JOIN sys.tables t ON t.object_id = ps.object_id
    JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE ps.index_id IN (0, 1) AND s.name = :schema
    GROUP BY t.name
"""


def _rows(conn, sql, schema):
    return list(conn.execute(text(sql), {"schema": schema}).mappings())


# ─────────────────────────────────────────────────────────────────────────
# Model assembly + edge inference
# ─────────────────────────────────────────────────────────────────────────
def assemble_model(schema, tbl_rows, col_rows, pk_rows, fk_rows, rc_rows,
                   overrides=None):
    """Pure assembly from raw catalog rows → testable without a DB."""
    oid_name = {r["object_id"]: r["table_name"] for r in tbl_rows}
    rowcounts = {r["table_name"]: int(r["row_count"] or 0) for r in rc_rows}

    pk_cols: dict[str, set] = {}
    for r in pk_rows:
        pk_cols.setdefault(r["table_name"], set()).add(r["column_name"])

    # Declared FK edges + the child columns that participate in them.
    decl_edges = []
    decl_seen = set()
    fk_child_cols: dict[str, set] = {}
    for r in fk_rows:
        e = (r["parent_table"], r["child_table"], r["child_col"])
        decl_edges.append({"parent": e[0], "child": e[1],
                           "col": e[2], "inferred": False})
        decl_seen.add((e[0].lower(), e[1].lower(), e[2].lower()))
        fk_child_cols.setdefault(r["child_table"], set()).add(r["child_col"])

    # Build the table → columns structure.
    tables: dict[str, dict] = {}
    for oid, tname in oid_name.items():
        tables[tname] = {
            "columns": [], "row_count": rowcounts.get(tname, 0),
            "area": assign_area(tname, overrides),
            "pk": pk_cols.get(tname, set()),
        }
    for r in col_rows:
        tname = oid_name.get(r["object_id"])
        if tname is None:
            continue
        cname = r["column_name"]
        tables[tname]["columns"].append({
            "name": cname,
            "data_type": r["data_type"],
            "max_length": r["max_length"],
            "precision": r["precision"],
            "scale": r["scale"],
            "is_nullable": bool(r["is_nullable"]),
            "is_pk": cname in tables[tname]["pk"],
            "is_fk": cname in fk_child_cols.get(tname, set()),
        })

    # ── Inferred edges ────────────────────────────────────────────────
    # 1) UWI federation: any non-master table carrying a `uwi` column links
    #    to whichever table has `uwi` as its primary key (dv_well).
    uwi_parent = None
    for tname, t in tables.items():
        if any(c.lower() == "uwi" for c in t["pk"]):
            uwi_parent = tname
            break

    # 2) `<base>_id` links to a table whose sole PK is that exact column.
    pk_name_owner: dict[str, list] = {}
    for tname, t in tables.items():
        if len(t["pk"]) == 1:
            (only,) = tuple(t["pk"])
            pk_name_owner.setdefault(only.lower(), []).append(tname)

    inferred = []
    inf_seen = set()

    def _add_inferred(parent, child, col):
        key = (parent.lower(), child.lower(), col.lower())
        if parent == child or key in decl_seen or key in inf_seen:
            return
        inf_seen.add(key)
        inferred.append({"parent": parent, "child": child,
                         "col": col, "inferred": True})
        # surface the join key as an FK-ish column in the child
        for c in tables[child]["columns"]:
            if c["name"].lower() == col.lower():
                c["is_fk"] = True

    # single-PK tables, for the name-based fallback below
    single_pk_tables = [tn for tn, t in tables.items() if len(t["pk"]) == 1]

    for tname, t in tables.items():
        colnames = [c["name"] for c in t["columns"]]
        if uwi_parent and tname != uwi_parent:
            if any(c.lower() == "uwi" for c in colnames):
                _add_inferred(uwi_parent, tname, "uwi")
        for c in colnames:
            cl = c.lower()
            if not cl.endswith("_id") or cl in t["pk"]:
                continue
            # 1) exact: <base>_id matches a table whose sole PK is <base>_id
            owners = pk_name_owner.get(cl, [])
            if len(owners) == 1 and owners[0] != tname:
                _add_inferred(owners[0], tname, c)
                continue
            # 2) name-based fallback (catches catalog schemas whose PKs aren't
            #    named <base>_id): link <base>_id to the single other single-PK
            #    table whose name contains <base>. e.g. user_id -> inventory_user,
            #    group_id -> inventory_group.
            base = cl[:-3]  # strip "_id"
            if len(base) < 3:
                continue
            cand = [p for p in single_pk_tables
                    if p != tname and base in p.lower()]
            if len(cand) == 1:
                _add_inferred(cand[0], tname, c)

    edges = decl_edges + inferred

    # Well master = the table whose PK is `uwi` (dv_well), used for the
    # headline well-count metric. Falls back to a table literally named
    # dv_well. None for non-well schemas (file_catalog, las_catalog…).
    well_table = uwi_parent
    if not well_table:
        well_table = next((t for t in tables if t.lower() == "dv_well"), None)
    well_count = tables[well_table]["row_count"] if well_table else None

    # areas: ordered dict of area → [table names]
    areas: dict[str, list] = {a: [] for a in AREA_ORDER}
    for tname in sorted(tables):
        areas.setdefault(tables[tname]["area"], []).append(tname)
    areas = {a: areas[a] for a in AREA_ORDER if areas.get(a)}

    return {"schema": schema, "tables": tables, "edges": edges,
            "areas": areas, "well_table": well_table,
            "well_count": well_count}


def build_model(engine, schema="dataview", overrides=None):
    """Query the live catalog and assemble the model."""
    with engine.connect() as conn:
        tbl = _rows(conn, _Q_TABLES, schema)
        col = _rows(conn, _Q_COLUMNS, schema)
        pk = _rows(conn, _Q_PKS, schema)
        fk = _rows(conn, _Q_FKS, schema)
        rc = _rows(conn, _Q_ROWCOUNTS, schema)
    return assemble_model(schema, tbl, col, pk, fk, rc, overrides)


def connection_info(engine):
    """(server, database) for the engine's live connection — so the page can
    show exactly which database it's reading, not assume."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT @@SERVERNAME AS srv, DB_NAME() AS db")
        ).mappings().first()
    return (row["srv"], row["db"]) if row else ("?", "?")


def list_schemas(engine):
    """User schemas in the connected database that actually contain tables."""
    sql = """
        SELECT DISTINCT s.name AS schema_name
        FROM sys.schemas s
        JOIN sys.tables  t ON t.schema_id = s.schema_id
        ORDER BY s.name
    """
    with engine.connect() as conn:
        return [r["schema_name"] for r in conn.execute(text(sql)).mappings()]


# ─────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────
def format_type(col: dict) -> str:
    """Human-friendly SQL type for the data dictionary, e.g. nvarchar(50)."""
    t = col["data_type"]
    ml = col["max_length"]
    if t in ("nvarchar", "nchar"):
        return f"{t}(MAX)" if ml == -1 else f"{t}({ml // 2})"
    if t in ("varchar", "char", "varbinary", "binary"):
        return f"{t}(MAX)" if ml == -1 else f"{t}({ml})"
    if t in ("decimal", "numeric"):
        return f"{t}({col['precision']},{col['scale']})"
    return t


def mermaid_type(col: dict) -> str:
    """Single-token type for a Mermaid erDiagram attribute line."""
    return re.sub(r"\W", "", col["data_type"]) or "x"


def _ent(name: str) -> str:
    """Mermaid-safe entity name."""
    return re.sub(r"\W", "_", name).upper()


def _key_columns(t: dict, limit: int = 10) -> list:
    """PK + join-key columns, for compact entity boxes in area diagrams."""
    keys = [c for c in t["columns"]
            if c["is_pk"] or c["is_fk"]
            or c["name"].lower() == "uwi"
            or c["name"].lower().endswith("_id")]
    # de-dup preserving order
    seen, out = set(), []
    for c in keys:
        if c["name"] not in seen:
            seen.add(c["name"])
            out.append(c)
    return out[:limit]


def build_area_mermaid(model: dict, area: str, limit: int = 10) -> str:
    """erDiagram for one subject area: its tables (key columns) + parents."""
    tables = model["tables"]
    area_tables = [t for t in model["areas"].get(area, [])]
    area_set = set(area_tables)

    # include parent tables referenced from this area as context
    ctx = set()
    rel = []
    for e in model["edges"]:
        if e["child"] in area_set:
            rel.append(e)
            if e["parent"] not in area_set:
                ctx.add(e["parent"])

    lines = ["erDiagram"]
    for tname in area_tables + sorted(ctx):
        t = tables.get(tname)
        if not t:
            continue
        cols = _key_columns(t, limit) if tname in area_set else [
            c for c in t["columns"] if c["is_pk"]]
        lines.append(f"    {_ent(tname)} {{")
        if not cols:
            lines.append("        x none")
        for c in cols:
            tag = "PK" if c["is_pk"] else ("FK" if c["is_fk"] else "")
            lines.append(f"        {mermaid_type(c)} {c['name']} {tag}".rstrip())
        lines.append("    }")
    for e in rel:
        if e["parent"] not in tables:
            continue
        label = e["col"] + (" (inf)" if e["inferred"] else "")
        lines.append(f'    {_ent(e["parent"])} ||--o{{ {_ent(e["child"])} '
                     f': "{label}"')
    return "\n".join(lines)


def build_overview_mermaid(model: dict) -> str:
    """High-level flowchart: subject areas around the Wells hub, with counts."""
    areas = model["areas"]
    lines = ["flowchart LR"]
    node_id = {a: _ent(a) for a in areas}
    for a, tabs in areas.items():
        meta = AREA_META[a]
        rows = sum(model["tables"][t]["row_count"] for t in tabs)
        lab = (f'{meta["icon"]} {meta["label"]}<br/>'
               f'{len(tabs)} table{"" if len(tabs) == 1 else "s"} · '
               f'{rows:,} rows')
        lines.append(f'    {node_id[a]}["{lab}"]')
    hub = node_id.get("wells")
    if hub:
        for a in areas:
            if a != "wells":
                lines.append(f"    {hub} --- {node_id[a]}")
    for a in areas:
        meta = AREA_META[a]
        lines.append(f"    style {node_id[a]} fill:{meta['color']}22,"
                     f"stroke:{meta['color']},color:#e8eef2")
    return "\n".join(lines)


# ── Graphviz DOT (for local SVG/PNG rendering via the `dot` engine) ────────
def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def build_overview_dot(model: dict) -> str:
    """DOT flowchart of subject areas around the Wells hub (no emoji — keeps
    fonts portable in SVG)."""
    areas = model["areas"]
    nid = {a: _ent(a) for a in areas}
    lines = [
        "digraph overview {",
        '  rankdir=LR; bgcolor="transparent";',
        '  node [shape=box, style="filled,rounded", fontname="Helvetica",'
        ' fontcolor="white", color="#2a2f3a"];',
        '  edge [dir=none, color="#888780"];',
    ]
    for a, tabs in areas.items():
        meta = AREA_META[a]
        rows = sum(model["tables"][t]["row_count"] for t in tabs)
        lab = (f'{meta["label"]}\\n{len(tabs)} '
               f'table{"" if len(tabs) == 1 else "s"} · {rows:,} rows')
        lines.append(f'  {nid[a]} [label="{lab}", fillcolor="{meta["color"]}"];')
    hub = nid.get("wells")
    if hub:
        for a in areas:
            if a != "wells":
                lines.append(f"  {hub} -> {nid[a]};")
    lines.append("}")
    return "\n".join(lines)


def build_area_dot(model: dict, area: str, limit: int = 10) -> str:
    """DOT erDiagram for one subject area: its tables (key columns) + parents,
    rendered as classic record/entity boxes coloured by area."""
    tables = model["tables"]
    area_tables = list(model["areas"].get(area, []))
    area_set = set(area_tables)

    ctx, rel = set(), []
    for e in model["edges"]:
        if e["child"] in area_set:
            rel.append(e)
            if e["parent"] not in area_set:
                ctx.add(e["parent"])

    lines = [
        "digraph erd {",
        '  rankdir=LR; bgcolor="transparent"; nodesep=0.4; ranksep=0.8;',
        '  node [shape=plaintext, fontname="Helvetica"];',
    ]

    def entity(tname: str, full: bool):
        t = tables.get(tname)
        if not t:
            return None
        hdr = AREA_META[t["area"]]["color"]
        cols = (_key_columns(t, limit) if full
                else [c for c in t["columns"] if c["is_pk"]])
        rows = ""
        for c in cols:
            tag = "PK" if c["is_pk"] else ("FK" if c["is_fk"] else "")
            tagcell = f'<font color="#7a7f87">{tag}</font>' if tag else " "
            rows += (f'<tr><td align="left">{_esc(c["name"])}</td>'
                     f'<td align="left">{tagcell}</td></tr>')
        if not rows:
            rows = '<tr><td colspan="2"> </td></tr>'
        label = (
            '<<table border="0" cellborder="1" cellspacing="0" cellpadding="4" '
            'bgcolor="#f7f9fc">'
            f'<tr><td colspan="2" bgcolor="{hdr}">'
            f'<font color="white"><b>{_esc(tname)}</b></font></td></tr>'
            f'{rows}</table>>')
        return f"  {_ent(tname)} [label={label}];"

    for tname in area_tables:
        ent = entity(tname, True)
        if ent:
            lines.append(ent)
    for tname in sorted(ctx):
        ent = entity(tname, False)
        if ent:
            lines.append(ent)
    for e in rel:
        if e["parent"] not in tables:
            continue
        style = "dashed" if e["inferred"] else "solid"
        lines.append(
            f'  {_ent(e["parent"])} -> {_ent(e["child"])} '
            f'[label="{_esc(e["col"])}", style={style}, color="#9aa0a6", '
            f'fontname="Helvetica", fontsize=10, fontcolor="#9aa0a6", '
            f'arrowhead=crow];')
    lines.append("}")
    return "\n".join(lines)
