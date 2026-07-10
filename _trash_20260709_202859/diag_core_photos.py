"""
diag_core_photos.py — pinpoint why core photos aren't rendering in the scout ticket.

Walks the chain the scout ticket relies on:
    dv_well_core_photo rows  ->  active_ind  ->  path column  ->  file exists on disk

Run:
    python diag_core_photos.py                 # auto-picks a UWI with the most photos
    python diag_core_photos.py US42317...0000  # check a specific UWI

No Streamlit. Fail-fast, prints everything it finds.
"""
import os
import sys
import pyodbc

# ── config ─────────────────────────────────────────────────────────
SERVER   = r"127.0.0.1\SQLEXPRESS"
DATABASE = "DataView"
DRIVER   = "ODBC Driver 17 for SQL Server"
SCHEMA   = "dataview"
TABLE    = "dv_well_core_photo"

# The scout ticket's photo query reads this column. If the loader populated
# a different one, the diagnostic will surface it below.
SCOUT_PATH_COL = "file_path"
# ───────────────────────────────────────────────────────────────────


def connect():
    cs = (f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={DATABASE};"
          f"Trusted_Connection=yes;")
    return pyodbc.connect(cs, timeout=10)


def main():
    cn = connect()
    cur = cn.cursor()

    # 1) What columns actually exist on the photo table?
    cur.execute("""
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """, SCHEMA, TABLE)
    cols = cur.fetchall()
    col_names = [c[0] for c in cols]
    print("=" * 64)
    print(f"{SCHEMA}.{TABLE} columns:")
    for name, dtype in cols:
        print(f"   {name:<22} {dtype}")
    print()

    # Identify path-like columns
    path_like = [c for c in col_names
                 if c.lower() in ("file_path", "image_path", "path", "full_path")]
    print(f"Path-like columns present: {path_like or '(none!)'}")
    if SCOUT_PATH_COL not in col_names:
        print(f"  *** Scout ticket reads '{SCOUT_PATH_COL}' but that column "
              f"does NOT exist. This alone breaks rendering. ***")
        # fall back to whatever path column we did find, for the disk check
    use_col = SCOUT_PATH_COL if SCOUT_PATH_COL in col_names else (
        path_like[0] if path_like else None)
    print(f"Using '{use_col}' for the disk-existence check.\n")

    # 2) active_ind distribution (the query filters active_ind='Y')
    if "active_ind" in col_names:
        cur.execute(f"""
            SELECT COALESCE(active_ind,'(null)') ai, COUNT(*) n
            FROM {SCHEMA}.{TABLE} GROUP BY active_ind ORDER BY n DESC
        """)
        print("active_ind distribution (query keeps only 'Y'):")
        for ai, n in cur.fetchall():
            flag = "" if ai == "Y" else "   <- filtered OUT by scout query"
            print(f"   {ai:<8} {n:>8,}{flag}")
        print()
    else:
        print("No active_ind column — scout query's AND active_ind='Y' "
              "would error. Check the query.\n")

    # 3) Pick the target UWI
    if len(sys.argv) > 1:
        uwi = sys.argv[1].strip()
    else:
        cur.execute(f"""
            SELECT TOP 1 uwi, COUNT(*) n
            FROM {SCHEMA}.{TABLE}
            WHERE active_ind = 'Y'
            GROUP BY uwi ORDER BY n DESC
        """)
        row = cur.fetchone()
        if not row:
            print("No rows with active_ind='Y' in the table at all. "
                  "That's why the ticket is empty.")
            return
        uwi = row[0]
        print(f"Auto-picked UWI with most active photos: {uwi} ({row[1]} photos)\n")

    # 4) Pull the exact rows the scout ticket would, then test the disk
    if not use_col:
        print("No path column to test — stopping.")
        return
    cur.execute(f"""
        SELECT photo_type, COALESCE(active_ind,'(null)'), [{use_col}]
        FROM {SCHEMA}.{TABLE}
        WHERE uwi = ?
        ORDER BY photo_type
    """, uwi)
    rows = cur.fetchall()
    print("=" * 64)
    print(f"Photos for {uwi}:  {len(rows)} row(s) total")
    print("-" * 64)
    exists_n = active_n = 0
    for ptype, ai, path in rows:
        on_disk = bool(path) and os.path.exists(path)
        if ai == "Y":
            active_n += 1
        if on_disk:
            exists_n += 1
        mark = "OK " if on_disk else "MISS"
        print(f"  [{mark}] type={ptype:<10} active={ai:<6} {path}")
    print("-" * 64)
    print(f"active='Y': {active_n}/{len(rows)}     files on disk: "
          f"{exists_n}/{len(rows)}")
    print()

    # 5) Verdict
    print("=" * 64)
    if exists_n == 0:
        print("VERDICT: rows exist but NO file resolves on disk.")
        print("  -> path-repoint problem. The baked-in absolute paths don't")
        print("     match where the images actually live now. Tell me the")
        print("     real folder and I'll write the UPDATE pass.")
    elif active_n == 0:
        print("VERDICT: files exist but none are active_ind='Y'.")
        print("  -> the scout query filters them all out. Either flip them to")
        print("     'Y' or relax the filter.")
    else:
        print("VERDICT: rows active AND files on disk for this UWI.")
        print("  -> data is fine; the break is in render/extension/mime. Send")
        print("     me one resolved path's file extension and I'll check")
        print("     _photo_to_b64 / mime handling.")

    cn.close()


if __name__ == "__main__":
    try:
        main()
    except pyodbc.Error as e:
        print("DB ERROR:", e)
        sys.exit(1)
