"""
generate_core_images.py
=======================
Generates synthetic core tray photos and thin section images
for DataView well core records.

Reads core records from dataview.dv_well_core, generates:
  - Core tray photo  (raw\core_photos\<uwi>\tray_NNN.jpg)
  - UV light photo   (raw\core_photos\<uwi>\tray_NNN_uv.jpg)
  - Thin section     (raw\core_photos\<uwi>\thin_NNN.jpg)

Updates photo_folder_path, photo_count, has_uv_photos,
has_thin_section_photos in dv_well_core.

Usage:
    python generate_core_images.py
    python generate_core_images.py --out "C:\\Bulk\\raw\\core_photos"
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    sys.exit("pip install Pillow")

try:
    import urllib.parse
    from sqlalchemy import create_engine, text
    import pandas as pd
except ImportError:
    sys.exit("pip install sqlalchemy pyodbc pandas")

# ── Connection ────────────────────────────────────────────────────────
SERVER   = r"127.0.0.1\SQLEXPRESS"
DATABASE = "DataView"

cs  = (f"DRIVER={{ODBC Driver 17 for SQL Server}};"
       f"SERVER={SERVER};DATABASE={DATABASE};Trusted_Connection=yes;")
eng = create_engine(
    "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(cs),
    fast_executemany=True,
)

# ── Lithology color palettes ──────────────────────────────────────────
LITH_COLORS = {
    "SANDSTONE":            [(194, 178, 128), (210, 195, 145), (180, 165, 115)],
    "LIMESTONE":            [(180, 180, 200), (165, 165, 185), (195, 195, 210)],
    "DOLOMITE":             [(200, 190, 160), (185, 175, 148), (215, 205, 170)],
    "SHALE":                [(90,  100, 110), (80,  90,  100), (100, 110, 120)],
    "SILTSTONE":            [(160, 145, 120), (175, 160, 135), (145, 130, 108)],
    "WACKESTONE":           [(170, 175, 190), (155, 160, 175), (185, 190, 205)],
    "PACKSTONE":            [(175, 172, 185), (162, 160, 172), (188, 185, 198)],
    "GRAINSTONE":           [(190, 185, 165), (178, 172, 155), (202, 198, 178)],
    "MUDSTONE":             [(120, 115, 110), (110, 105, 100), (130, 125, 120)],
    "SANDY DOLOMITE":       [(205, 188, 148), (190, 175, 135), (220, 202, 162)],
    "CALCAREOUS SANDSTONE": [(200, 183, 140), (185, 168, 128), (215, 198, 153)],
}
DEFAULT_COLORS = [(180, 170, 155), (165, 155, 142), (195, 185, 168)]

# ── Image generators ──────────────────────────────────────────────────

def _lith_colors(lithology: str):
    key = (lithology or "").upper().strip()
    return LITH_COLORS.get(key, DEFAULT_COLORS)


def generate_core_tray(
    uwi: str,
    core_num: int,
    lithology: str,
    top_depth: float,
    base_depth: float,
    recovery_pct: float,
    width: int = 800,
    height: int = 200,
    uv: bool = False,
) -> Image.Image:
    """Generate a horizontal core tray photo."""
    rng    = random.Random(hash(uwi + str(core_num) + str(uv)))
    colors = _lith_colors(lithology)
    img    = Image.new("RGB", (width, height), (40, 40, 40))
    draw   = ImageDraw.Draw(img)

    # Core tray background
    draw.rectangle([0, 0, width, height], fill=(50, 45, 42))

    # Core sections (simulate recovery gaps)
    section_w  = width - 40
    recovered  = int(section_w * (recovery_pct / 100))
    x0, y0     = 20, 20
    y1          = height - 20

    # Main core body
    segments = rng.randint(4, 10)
    seg_w    = recovered // segments
    x        = x0
    for i in range(segments):
        w = seg_w + rng.randint(-10, 10)
        c = colors[i % len(colors)]
        # Add slight variation per segment
        c = tuple(min(255, max(0, v + rng.randint(-12, 12))) for v in c)
        draw.rectangle([x, y0, x+w, y1], fill=c)
        # Lamination lines
        for _ in range(rng.randint(0, 4)):
            ly = rng.randint(y0+5, y1-5)
            lc = tuple(max(0, v - 30) for v in c)
            draw.line([x, ly, x+w, ly], fill=lc, width=1)
        # Fractures
        if rng.random() < 0.3:
            fx  = x + rng.randint(5, w-5)
            ang = rng.uniform(-0.3, 0.3)
            draw.line([fx, y0, fx + int((y1-y0)*ang), y1],
                      fill=(60, 55, 50), width=2)
        x += w + rng.randint(2, 8)  # gap between segments

    # UV effect — fluorescence on oil-bearing intervals
    if uv:
        overlay = Image.new("RGB", (width, height), (0, 0, 0))
        odraw   = ImageDraw.Draw(overlay)
        odraw.rectangle([0, 0, width, height], fill=(10, 5, 20))
        # Draw fluorescent patches
        for i in range(segments):
            if rng.random() < 0.5:
                sx = x0 + i * (seg_w + 5)
                sw = rng.randint(seg_w // 3, seg_w)
                intensity = rng.randint(80, 200)
                fc = (intensity, intensity // 3, 0)  # amber/orange fluorescence
                odraw.rectangle([sx, y0, sx+sw, y1], fill=fc)
        img = Image.blend(img, overlay, alpha=0.7)
        draw = ImageDraw.Draw(img)

    # Depth labels
    draw.text((x0, 2), f"{top_depth:.1f} ft", fill=(220, 220, 220))
    draw.text((width - 80, 2), f"{base_depth:.1f} ft", fill=(220, 220, 220))
    draw.text((x0, height - 16),
              f"Core {core_num} · {lithology or 'Unknown'} · {recovery_pct:.0f}% recovery",
              fill=(180, 180, 180))

    # Subtle noise texture
    img = img.filter(ImageFilter.GaussianBlur(0.5))
    return img


def generate_thin_section(
    uwi: str,
    core_num: int,
    sample_depth: float,
    lithology: str,
    porosity_pct: float,
    size: int = 512,
) -> Image.Image:
    """Generate a synthetic thin section image (plane polarised light)."""
    rng  = random.Random(hash(uwi + str(core_num) + str(sample_depth)))
    img  = Image.new("RGB", (size, size), (240, 235, 220))
    draw = ImageDraw.Draw(img)

    colors = _lith_colors(lithology)
    n_grains = rng.randint(30, 80)

    for _ in range(n_grains):
        cx  = rng.randint(20, size - 20)
        cy  = rng.randint(20, size - 20)
        rx  = rng.randint(8, 35)
        ry  = rng.randint(6, 28)
        c   = colors[rng.randint(0, len(colors)-1)]
        c   = tuple(min(255, max(0, v + rng.randint(-20, 20))) for v in c)
        draw.ellipse([cx-rx, cy-ry, cx+rx, cy+ry], fill=c,
                     outline=tuple(max(0,v-40) for v in c))
        # Cleavage lines
        if rng.random() < 0.4:
            angle = rng.uniform(0, math.pi)
            dx = int(rx * math.cos(angle))
            dy = int(rx * math.sin(angle))
            draw.line([cx-dx, cy-dy, cx+dx, cy+dy],
                      fill=tuple(max(0,v-50) for v in c), width=1)

    # Pore space (dark)
    n_pores = int(n_grains * porosity_pct / 100 * 2)
    for _ in range(n_pores):
        px = rng.randint(10, size-10)
        py = rng.randint(10, size-10)
        pr = rng.randint(2, 10)
        draw.ellipse([px-pr, py-pr, px+pr, py+pr], fill=(20, 18, 15))

    # Scale bar
    bar_x, bar_y = size - 80, size - 20
    draw.rectangle([bar_x, bar_y-4, bar_x+60, bar_y], fill=(30,30,30))
    draw.text((bar_x, bar_y - 18), "0.5 mm", fill=(30,30,30))

    # Label
    draw.text((5, 5),
              f"{sample_depth:.1f} ft · {lithology or ''} · φ={porosity_pct:.1f}%",
              fill=(30, 30, 30))

    img = img.filter(ImageFilter.GaussianBlur(0.3))
    return img


# ── Main ──────────────────────────────────────────────────────────────

def main(out_root: str = r"raw\core_photos") -> None:
    out = Path(out_root)

    with eng.connect() as con:
        cores = pd.read_sql(text("""
            SELECT c.uwi, c.core_id, c.core_num, c.core_type,
                   c.top_depth, c.base_depth, c.recovery_pct,
                   c.strat_unit_name, c.has_uv_photos
            FROM dataview.dv_well_core c
            WHERE c.active_ind='Y'
            ORDER BY c.uwi, c.core_num
        """), con).to_dict("records")

        samples = pd.read_sql(text("""
            SELECT uwi, core_id, sample_id, sample_type, sample_depth,
                   lithology, hydrocarbon_show,
                   porosity_frac * 100.0          porosity_pct,
                   permeability_air_md             permeability_md,
                   bulk_density_g_cc               bulk_density,
                   grain_density_g_cc              grain_density,
                   water_saturation_frac * 100.0   water_saturation,
                   oil_saturation_frac  * 100.0    oil_saturation
            FROM dataview.dv_well_core_sample
            WHERE active_ind='Y'
            ORDER BY uwi, sample_depth
        """), con).to_dict("records")

    print(f"Generating images for {len(cores)} cores, "
          f"{len(samples)} samples...")

    sample_map = {}
    for s in samples:
        sample_map.setdefault(s["core_id"], []).append(s)

    updates = []

    for core in cores:
        uwi      = core["uwi"]
        core_id  = core["core_id"]
        core_num = int(core["core_num"] or 1)
        lith     = core.get("strat_unit_name") or "SANDSTONE"
        top_d    = float(core.get("top_depth") or 0)
        base_d   = float(core.get("base_depth") or top_d + 100)
        rec_pct  = float(core.get("recovery_pct") or 80)
        has_uv   = str(core.get("has_uv_photos","N")).upper() == "Y"

        folder   = out / uwi
        folder.mkdir(parents=True, exist_ok=True)

        photo_count = 0

        # Tray photo (white light)
        tray_img = generate_core_tray(
            uwi, core_num, lith, top_d, base_d, rec_pct)
        tray_path = folder / f"tray_{core_num:03d}.jpg"
        tray_img.save(tray_path, "JPEG", quality=85)
        photo_count += 1
        print(f"  {uwi} core {core_num}: tray photo → {tray_path}")

        # UV photo
        if has_uv:
            uv_img  = generate_core_tray(
                uwi, core_num, lith, top_d, base_d, rec_pct, uv=True)
            uv_path = folder / f"tray_{core_num:03d}_uv.jpg"
            uv_img.save(uv_path, "JPEG", quality=85)
            photo_count += 1

        # Thin sections for samples
        for samp in sample_map.get(core_id, []):
            poro  = float(samp.get("porosity_pct") or 8)
            depth = float(samp.get("sample_depth") or top_d)
            slith = samp.get("lithology") or lith
            ts    = generate_thin_section(
                uwi, core_num, depth, slith, poro)
            ts_path = folder / f"thin_{core_num:03d}_{int(depth):05d}ft.jpg"
            ts.save(ts_path, "JPEG", quality=85)
            photo_count += 1

        updates.append({
            "core_id":       core_id,
            "photo_folder":  str(folder),
            "photo_count":   photo_count,
        })

    # Update DB
    with eng.begin() as con:
        for u in updates:
            con.execute(text("""
                UPDATE dataview.dv_well_core
                SET photo_folder_path = :folder,
                    photo_count       = :count,
                    row_changed_date  = GETDATE()
                WHERE core_id = :cid
            """), {"folder": u["photo_folder"],
                   "count":  u["photo_count"],
                   "cid":    u["core_id"]})

    total = sum(u["photo_count"] for u in updates)
    print(f"\nDone — {total} images across {len(updates)} cores")
    print(f"Saved to: {out.resolve()}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"raw\core_photos",
                    help="Output folder for core images")
    args = ap.parse_args()
    main(args.out)
