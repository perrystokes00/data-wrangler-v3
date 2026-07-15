"""
gen_relax_ddl.py — emit ALTER TABLE statements that relax over-constrained NOT NULL
measurement columns, from dataview_schema_full.json.

Policy (what stays NOT NULL):
  * primary key columns                      — identity, never null
  * uwi                                      — every row belongs to a well
  * active_ind / row_created_by / row_created_date  — governance stamps the loader sets
  * source                                   — provenance; the loader always sets it
Everything else currently NOT NULL is relaxed: measurements, dates, units, FK ids.
Rationale: a scout ticket can't know cement_volume_sacks; requiring it means only a full
cementing report could ever populate dv_well_casing. PPDM practice is to constrain
identity and let measurements be absent.
"""
import json
import sys

KEEP = {"active_ind", "row_created_by", "row_created_date", "source", "uwi"}

# Not in the PK, but real business identity — a curve with no mnemonic, or a top with no
# strat unit, is meaningless rather than merely unmeasured. These stay NOT NULL.
KEEP_EXTRA = {
    "dv_well_log_curve": {"mnemonic"},
    "dv_well_formation_top": {"strat_unit_id"},
}

# tables the document/log extractors write
TABLES = [
    "dv_well", "dv_well_formation_top", "dv_well_log", "dv_well_log_curve", "dv_well_core",
    "dv_well_dir_srvy_hdr", "dv_well_dir_srvy_sta", "dv_well_casing", "dv_well_stimulation",
    "dv_well_dst", "dv_well_dst_period", "dv_well_pressure", "dv_well_petro_interp",
    "dv_well_petro_zone",
]


def coltype(c):
    t = c["type"].lower()
    n = c.get("max_len")
    p, s = c.get("precision"), c.get("scale")
    if t in ("nvarchar", "varchar", "char", "nchar", "binary", "varbinary"):
        if n in (-1, None):
            return f"{t}(max)"
        return f"{t}({n})"
    if t in ("numeric", "decimal") and p is not None:
        return f"{t}({p},{s or 0})"
    if t in ("datetime2", "time") and p is not None:
        return f"{t}({p})"
    return t


def main(path, schema="dataview"):
    d = json.load(open(path, encoding="utf-8"))
    T = d["tables"]
    out = []
    out.append("-- Relax over-constrained NOT NULL measurement columns.")
    out.append(f"-- Generated from {path.split('/')[-1]} (db {d.get('database')}, "
               f"schema {d.get('schema')}, snapshot {d.get('generated_at')}).")
    out.append("-- KEEPS NOT NULL: primary key, uwi, active_ind, source, row_created_by/date.")
    out.append("-- Review before running. Take a backup first.")
    out.append("")
    total = 0
    for tbl in TABLES:
        if tbl not in T:
            out.append(f"-- !! {tbl} not in schema snapshot — skipped")
            continue
        meta = T[tbl]
        pk = {c.lower() for c in (meta.get("primary_key") or [])}
        keep = KEEP | pk | KEEP_EXTRA.get(tbl, set())
        relax = [c for c in meta["columns"]
                 if not c["nullable"] and c["name"].lower() not in keep
                 and c["type"].lower() not in ("geography", "geometry", "timestamp")]
        if not relax:
            continue
        out.append(f"-- {tbl}: {len(relax)} column(s) relaxed "
                   f"(PK {', '.join(sorted(pk)) or 'n/a'} kept NOT NULL)")
        for c in relax:
            out.append(f"ALTER TABLE {schema}.{tbl} ALTER COLUMN [{c['name']}] {coltype(c)} NULL;")
            total += 1
        out.append("GO")
        out.append("")
    out.append(f"-- {total} column(s) relaxed in total.")
    return "\n".join(out)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads/dataview_schema_full.json"
    print(main(src))
