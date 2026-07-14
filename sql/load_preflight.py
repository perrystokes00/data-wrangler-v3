r"""
load_preflight.py — read a directory of CSVs and produce a DRY-RUN load plan against a
DataView catalog. Writes NOTHING. Explains every call.

  py load_preflight.py <dir> [--catalog dataview_fk_catalog.json]

The catalog is your generated dataview_fk_catalog.json (keys: fk_constraints, table_cols,
table_pk, table_kind). Reference files (matching dv_r_* lookups) are classified separately
from data files (matching dv_ entity tables); load order is a topological sort of the
declared FK graph; anything a data file references that isn't satisfied by the drop lands
on the Match-and-Map worklist.
"""
import sys, os, json, glob, csv
from collections import defaultdict

def norm(c): return c.strip().upper().replace(" ", "_")

def load_catalog(path):
    cat = json.load(open(path))
    return cat["fk_constraints"], cat["table_cols"], cat["table_kind"]

def read_header(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        row = next(csv.reader(fh), [])
    return {norm(c) for c in row if c.strip() and not c.lower().startswith("unnamed")}

def is_data_table(t):
    tl = t.lower()
    return tl.startswith("dv_") and not tl.startswith("dv_r_") \
        and tl not in ("dv_global_file_catalog", "dv_wl_file_catalog")

def is_ref_table(t):
    return t.lower().startswith("dv_r_")

def score(cols, tset):
    return len(cols & tset) / max(1, len(cols))

def filename_hint(fname, table):
    f = fname[:-4].upper().replace("DIR_SURVEY", "DIR_SRVY")
    t = table.replace("DV_", "")
    h = 0.0
    if t in f or f.replace("WELL_", "") in t: h += 0.15
    nudges = {
        ("well_picks.csv", "DV_WELL_FORMATION_TOP"): 0.25,
        ("well_dir_survey_hdr.csv", "DV_WELL_DIR_SRVY_HDR"): 0.30,
        ("well_dir_survey_data.csv", "DV_WELL_DIR_SRVY_STA"): 0.30,
    }
    return h + nudges.get((fname, table), 0.0)

def best(cols, fname, candidates):
    ranked = []
    for t, tset in candidates.items():
        ov = score(cols, tset)
        ranked.append((ov + filename_hint(fname, t), ov, t))
    ranked.sort(reverse=True)
    return ranked[0]                       # (adj_score, raw_overlap, table)

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    catpath = "dataview_fk_catalog.json"
    if "--catalog" in sys.argv:
        catpath = sys.argv[sys.argv.index("--catalog") + 1]
    directory = args[0] if args else "."

    FKC, COLS, KIND = load_catalog(catpath)
    DATA = {t: set(c) for t, c in COLS.items() if is_data_table(t)}
    REF  = {t: set(c) for t, c in COLS.items() if is_ref_table(t)}

    files = sorted(glob.glob(os.path.join(directory, "*.csv")))
    print(f"\nLOAD PRE-FLIGHT — {directory}   ({len(files)} CSVs)   · dry run, nothing written\n")

    # ---- classify + map ----
    mapping, refmap = {}, {}
    print("FILE → TABLE")
    for path in files:
        f = os.path.basename(path); cols = read_header(path)
        d_adj, d_ov, d_t = best(cols, f, DATA)
        r_adj, r_ov, r_t = best(cols, f, REF) if REF else (0, 0, None)
        # reference file if it fits a dv_r_ table clearly better than any data table
        if r_ov >= 0.5 and r_ov > d_ov:
            refmap[path] = r_t
            print(f"   {f:26s} → {r_t:26s} [REFERENCE {r_ov*100:.0f}%]")
        elif d_ov == 0:
            print(f"   {f:26s} → (no table matched — inspect: {sorted(cols)})")
        else:
            mapping[path] = d_t
            print(f"   {f:26s} → {d_t:26s} [DATA {d_ov*100:.0f}%]"
                  + ("  +hint" if d_adj > d_ov + 1e-6 else ""))

    matched = set(mapping.values()) | set(refmap.values())

    # ---- topological load order over declared FKs (references first) ----
    dep = defaultdict(set)
    for t in matched:
        for fk in FKC.get(t, []):
            p = fk["parent_table"]
            if p in matched and p != t:
                dep[t].add(p)
    order, seen = [], set()
    # references have no in-drop parents → naturally sort first
    while len(seen) < len(matched):
        prog = False
        for t in sorted(matched):
            if t not in seen and dep[t] <= seen:
                order.append(t); seen.add(t); prog = True
        if not prog:
            order += [t for t in sorted(matched) if t not in seen]; break

    inv = {v: os.path.basename(k) for k, v in {**mapping, **refmap}.items()}
    print("\nLOAD ORDER (topological — parents before children)")
    for i, t in enumerate(order, 1):
        kind = "ref " if is_ref_table(t) else "data"
        edges = [fk for fk in FKC.get(t, []) if fk["parent_table"] in matched]
        e = ("  ⟵ " + ", ".join(f"{'+'.join(fk['child_cols'])}→{fk['parent_table']}"
                                 for fk in edges)) if edges else ""
        print(f"   {i}. [{kind}] {t:24s} ({inv.get(t,'?')}){e}")

    # ---- Match-and-Map worklist: declared parents NOT satisfied by the drop ----
    need = defaultdict(list)
    for t in matched:
        for fk in FKC.get(t, []):
            p = fk["parent_table"]
            if p not in matched:
                need[p].append((t, "+".join(fk["child_cols"])))
    print(f"\nMATCH-AND-MAP WORKLIST — {len(need)} parent table(s) must be resolved first")
    print("(each blocks the child columns listed; resolve/create + remember, never null)")
    for p in sorted(need):
        kind = KIND.get(p, "?")
        childs = ", ".join(f"{c}.{col}" for c, col in need[p])
        print(f"   {p:26s} [{kind:9s}]  blocks: {childs}")

    print("\nVERDICT: map the flagged files, seed/resolve the worklist above, then the "
          "data graph loads in the order shown — as one transaction.")

if __name__ == "__main__":
    main()
