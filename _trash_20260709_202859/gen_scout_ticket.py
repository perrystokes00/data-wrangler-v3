r"""
gen_scout_ticket.py — generate a SYNTHETIC single-well scout ticket as a real TEXT-LAYER
PDF whose grid the scout parser can read. Key: the parser (_scout_grid_rows) splits
columns by literal '|' characters, so this draws '|' separators between cells. Header
rows (label row + value row) then split into columns and _scout_parse_header can zip
[API, WELL_NAME, WELL_TYPE, STATUS] correctly.

  pip install reportlab pdfplumber --break-system-packages
  py gen_scout_ticket.py --out scout_synth.pdf --uwi 15007243240000 --name "MAYBERRY V1-26"
"""
import sys, os
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

def arg(k, d=None):
    return sys.argv[sys.argv.index(k)+1] if k in sys.argv else d

OUT  = arg("--out", "scout_synth.pdf")
UWI  = arg("--uwi", "15007243240000")
NAME = arg("--name", "MAYBERRY V1-26")
API  = "".join(ch for ch in UWI if ch.isdigit()).ljust(14,"0")[:14]

c = canvas.Canvas(OUT, pagesize=letter)
W, H = letter
x0 = 0.5*inch
y = H - 0.7*inch
LH = 15

# column x-positions (points). '|' drawn at each boundary so the grid parser
# sees separators; cell text drawn just after each boundary.
def grid_row(cells, colx, size=9, bold=False):
    """Draw cells separated by '|' at the given column x-positions."""
    global y
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    # leading separator
    c.drawString(x0, y, "|")
    for i, cell in enumerate(cells):
        cx = colx[i]
        c.drawString(cx, y, str(cell))
        # trailing separator after this cell's column
        sep_x = colx[i+1]-8 if i+1 < len(colx) else colx[i] + 110
        c.drawString(sep_x, y, "|")
    y -= LH

def section(title):
    global y
    y -= 6
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x0, y, title); y -= LH+2

# ── title ──
c.setFont("Helvetica-Bold", 15); c.drawString(x0, y, "WELL SCOUT TICKET"); y -= 20
c.setFont("Helvetica", 9); c.drawString(x0, y, "DataView - Synthetic Test - ACTIVE"); y -= 22

# ── Well Header (4-col) ──
section("Well Header")
H4 = [x0+12, x0+150, x0+290, x0+410, x0+520]
grid_row(["API","Well Name","Well Type","Status"], H4, bold=True)
grid_row([API, NAME, "HORIZONTAL", "ACTIVE"], H4)
grid_row(["Operator","Field","County","State"], H4, bold=True)
grid_row(["Synthetic E&P","Wolfcamp Play","Martin","Texas"], H4)
grid_row(["Spud Date","Completion Date","Total Depth","Surface Location"], H4, bold=True)
grid_row(["2016-03-21","2016-08-26","13444 ft","32.127700N 101.560500W"], H4)
H3 = [x0+12, x0+150, x0+290, x0+430]
grid_row(["UWI","KB Elevation","Depth Datum"], H3, bold=True)
grid_row([UWI, "2850 ft", "KB"], H3)

# ── Formation Tops (5-col) ──
section("Stratigraphy - Formation Tops")
F5 = [x0+12, x0+130, x0+230, x0+330, x0+430, x0+520]
grid_row(["Formation","Top MD","Base MD","Net Pay","Fluid"], F5, bold=True)
for f,t,b in [("Clearfork",5660,6343),("Avalon Shale",7740,7922),("Bone Spring",8164,8593)]:
    grid_row([f, t, b, "-", "-"], F5)

# ── Directional Survey (7-col) ──
section("Directional Survey - stations")
S7 = [x0+12, x0+80, x0+150, x0+220, x0+300, x0+380, x0+460, x0+540]
grid_row(["MD","Inc","Azi","TVD","N/S","E/W","DLS"], S7, bold=True)
for s in [(163,3.37,316.10,160,3,2,2.16),(445,6.57,316.50,430,15,9,0.64),
          (671,7.69,314.90,646,26,15,1.91),(825,14.59,315.30,765,60,36,0.78),
          (1100,15.63,314.50,1014,86,52,1.52),(1360,22.05,312.10,1210,150,90,1.52),
          (1528,27.62,316.50,1317,211,127,1.35),(1764,25.67,314.90,1538,226,136,0.71),
          (2026,29.49,317.00,1727,299,179,2.81),(2276,35.93,314.30,1867,409,245,0.90)]:
    grid_row([str(v) for v in s], S7)

# ── DST (7-col) ──
section("DST - Drill Stem Tests")
D7 = [x0+12, x0+90, x0+150, x0+230, x0+310, x0+380, x0+470, x0+540]
grid_row(["Test Date","Type","Top MD","Base MD","Result","Max Oil","Max Gas"], D7, bold=True)
grid_row(["2021-05-01","DST","7190","7343","GAS","0","9298"], D7)

# ── Completion (6-col) ──
section("Completion Summary")
C6 = [x0+12, x0+100, x0+250, x0+340, x0+430, x0+500, x0+560]
grid_row(["Completion Date","Type","Orientation","Formation","Lateral","Stages"], C6, bold=True)
grid_row(["2016-08-26","Cased Hole Multistage Frac","Horizontal","Austin Chalk","7314","33"], C6)

c.showPage(); c.save()

# verify with the ACTUAL scout parser
try:
    sys.path.insert(0, r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3")
    sys.path.insert(0, r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3\modules")
    from pdf_survey_catalog import _scout_all_rows, _scout_parse_header
    rows = _scout_all_rows(OUT)
    h = _scout_parse_header(rows)
    print(f"generated: {OUT}")
    print(f"  header row[3-4]: {rows[3] if len(rows)>3 else '?'} / {rows[4] if len(rows)>4 else '?'}")
    print(f"  parsed WELL_NAME={h.get('WELL_NAME')!r} UWI={h.get('UWI')!r} API={h.get('API')!r}")
    ok = h.get('WELL_NAME') and h.get('API')
    print(f"  header parses correctly: {bool(ok)}")
except Exception as e:
    import pdfplumber
    with pdfplumber.open(OUT) as pdf:
        print("generated (parser not available to verify here):", OUT)
        print("first 300 chars:", (pdf.pages[0].extract_text() or "")[:300])
