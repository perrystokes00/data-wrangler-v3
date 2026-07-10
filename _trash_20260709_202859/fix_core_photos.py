"""
fix_core_photos.py — regenerate the synthetic core images AND re-point the DB
paths so dv_well_core_photo and the disk agree, making photos render in the
scout ticket.

What it does:
  1. Discovers the photo table's columns + identity/PK column at runtime.
  2. Reads every active_ind='Y' photo row.
  3. Regenerates a synthetic PNG for each row, styled by photo_type + lighting,
     written to  OUTPUT_ROOT / <uwi> / <filename>.
  4. Re-points file_path (+ file_name) via a single staging-table JOIN UPDATE.
     No per-row UPDATE loop against the real table.

Run:
    python fix_core_photos.py            # generate + repoint (commits)
    python fix_core_photos.py --dry      # generate images + preview, NO db write

Requires Pillow (you already use it for generate_core_images.py).
"""
import os
import sys
import pyodbc
from PIL import Image, ImageDraw, ImageFont

# ── config ─────────────────────────────────────────────────────────
SERVER   = r"127.0.0.1\SQLEXPRESS"
DATABASE = "DataView"
DRIVER   = "ODBC Driver 17 for SQL Server"
SCHEMA   = "dataview"
TABLE    = "dv_well_core_photo"

# Where images get written. Default: <this script's folder>\assets\core_photos
OUTPUT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "assets", "core_photos")

IMG_W, IMG_H = 640, 320
DRY = "--dry" in sys.argv
# ───────────────────────────────────────────────────────────────────


def _font(sz):
    try:
        return ImageFont.truetype("arial.ttf", sz)
    except Exception:
        return ImageFont.load_default()


def make_core_image(path, uwi, ptype, lighting, top, base, tray):
    """Synthetic core-tray / thin-section image, look varies by type+lighting."""
    uv = str(lighting).upper() == "UV"
    bg = (18, 18, 28) if uv else (236, 230, 222)
    img = Image.new("RGB", (IMG_W, IMG_H), bg)
    d = ImageDraw.Draw(img)

    ptype_u = str(ptype).upper()
    if ptype_u in ("TRAY", "SLAB", "OVERVIEW"):
        # stacked horizontal core segments
        n = 5
        pad, gap = 18, 8
        seg_h = (IMG_H - 70 - (n - 1) * gap) // n
        y = 50
        for i in range(n):
            if uv:
                # dark rock with bright fluorescence patches (oil shows)
                d.rectangle([pad, y, IMG_W - pad, y + seg_h], fill=(28, 30, 40))
                import random
                random.seed(hash((uwi, tray, i)) & 0xFFFF)
                for _ in range(14):
                    cx = random.randint(pad + 10, IMG_W - pad - 10)
                    cy = random.randint(y + 6, y + seg_h - 6)
                    r = random.randint(4, 12)
                    g = random.randint(160, 230)
                    d.ellipse([cx - r, cy - r, cx + r, cy + r],
                              fill=(g - 60, g, 80))
            else:
                shade = 150 - i * 14
                d.rectangle([pad, y, IMG_W - pad, y + seg_h],
                            fill=(shade, max(80, shade - 40), 60))
                for sx in range(pad + 6, IMG_W - pad, 22):
                    d.line([sx, y + 4, sx, y + seg_h - 4],
                           fill=(max(60, shade - 50), 50, 40), width=1)
            y += seg_h + gap
    else:
        # thin-section style: circular field of view
        cx, cy, r = IMG_W // 2, IMG_H // 2 + 8, 120
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  fill=(30, 32, 44) if uv else (210, 200, 188))
        import random
        random.seed(hash((uwi, ptype)) & 0xFFFF)
        for _ in range(70):
            gx = random.randint(cx - r + 8, cx + r - 8)
            gy = random.randint(cy - r + 8, cy + r - 8)
            if (gx - cx) ** 2 + (gy - cy) ** 2 > (r - 8) ** 2:
                continue
            gr = random.randint(5, 16)
            col = ((random.randint(150, 230), random.randint(180, 240), 90)
                   if uv else
                   (random.randint(120, 200),) * 3)
            d.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=col)

    # header bar + labels
    fg = (235, 235, 240) if uv else (40, 30, 25)
    d.rectangle([0, 0, IMG_W, 38], fill=(60, 90, 90) if not uv else (40, 50, 60))
    d.text((12, 10), f"{uwi}   {ptype_u} / {str(lighting).upper()}",
           fill=(245, 245, 245), font=_font(15))
    dep = ""
    try:
        if top is not None and base is not None:
            dep = f"{float(top):.0f}-{float(base):.0f} ft"
        elif top is not None:
            dep = f"{float(top):.0f} ft"
    except Exception:
        dep = ""
    if dep:
        d.text((12, IMG_H - 22), f"Tray {tray}   {dep}", fill=fg, font=_font(13))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG")


def main():
    cn = pyodbc.connect(
        f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={DATABASE};"
        f"Trusted_Connection=yes;", timeout=10)
    cur = cn.cursor()

    # discover columns
    cur.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA=? AND TABLE_NAME=? ORDER BY ORDINAL_POSITION
    """, SCHEMA, TABLE)
    cols = {r[0].lower() for r in cur.fetchall()}
    if not cols:
        print(f"Table {SCHEMA}.{TABLE} not found."); return

    # discover identity / PK column for the JOIN key
    cur.execute("""
        SELECT c.name FROM sys.identity_columns c
        JOIN sys.tables t ON t.object_id=c.object_id
        JOIN sys.schemas s ON s.schema_id=t.schema_id
        WHERE s.name=? AND t.name=?
    """, SCHEMA, TABLE)
    idrow = cur.fetchone()
    key_col = idrow[0] if idrow else None
    if not key_col:
        cur.execute("""
            SELECT kcu.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
              ON tc.CONSTRAINT_NAME=kcu.CONSTRAINT_NAME
            WHERE tc.TABLE_SCHEMA=? AND tc.TABLE_NAME=?
              AND tc.CONSTRAINT_TYPE='PRIMARY KEY'
        """, SCHEMA, TABLE)
        pk = cur.fetchall()
        key_col = pk[0][0] if len(pk) == 1 else None
    if not key_col:
        print("No single identity/PK column found — falling back to file_path "
              "as the join key (must be distinct).")
        key_col = "file_path"
    print(f"Join key: {key_col}")

    # build SELECT from columns that exist
    want = ["uwi", "photo_type", "lighting", "top_depth", "base_depth",
            "tray_num", "file_name", "file_path"]
    have = [c for c in want if c in cols]
    sel = [key_col] + [c for c in have if c != key_col]
    cur.execute(f"""
        SELECT {', '.join('['+c+']' for c in sel)}
        FROM {SCHEMA}.{TABLE}
        WHERE active_ind='Y'
    """)
    rows = [dict(zip(sel, r)) for r in cur.fetchall()]
    print(f"Active photo rows: {len(rows)}")
    if not rows:
        print("Nothing active to fix."); return

    # generate images + collect repoint tuples
    updates = []
    for r in rows:
        uwi = str(r.get("uwi", "UNKNOWN"))
        ptype = r.get("photo_type", "TRAY") or "TRAY"
        light = r.get("lighting", "WHITE") or "WHITE"
        tray = r.get("tray_num", 1) or 1
        fname = r.get("file_name") or \
            f"{uwi}_{tray}_{str(ptype).lower()}_{str(light).lower()}.png"
        if not str(fname).lower().endswith((".png", ".jpg", ".jpeg")):
            fname = f"{fname}.png"
        abs_path = os.path.join(OUTPUT_ROOT, uwi, fname)
        make_core_image(abs_path, uwi, ptype, light,
                        r.get("top_depth"), r.get("base_depth"), tray)
        updates.append((r[key_col], abs_path, fname))

    print(f"Generated {len(updates)} images under {OUTPUT_ROOT}")
    for k, p, _ in updates[:3]:
        print(f"   {key_col}={k}  ->  {p}")

    if DRY:
        print("\n--dry: images written, DB NOT updated.")
        return

    # staging + single JOIN UPDATE (no per-row UPDATE on real table)
    cur.execute("CREATE TABLE #px (k SQL_VARIANT, new_path NVARCHAR(500), "
                "new_name NVARCHAR(260))")
    cur.fast_executemany = True
    cur.executemany("INSERT INTO #px (k, new_path, new_name) VALUES (?,?,?)",
                    updates)
    set_name = ", file_name = s.new_name" if "file_name" in cols else ""
    cur.execute(f"""
        UPDATE p SET p.file_path = s.new_path {set_name}
        FROM {SCHEMA}.{TABLE} p
        JOIN #px s ON CAST(p.[{key_col}] AS NVARCHAR(500)) = CAST(s.k AS NVARCHAR(500))
    """)
    print(f"Re-pointed {cur.rowcount} rows.")
    cn.commit()
    cn.close()
    print("Done. Cold-start Streamlit and reopen a ticket.")


if __name__ == "__main__":
    try:
        main()
    except pyodbc.Error as e:
        print("DB ERROR:", e); sys.exit(1)
