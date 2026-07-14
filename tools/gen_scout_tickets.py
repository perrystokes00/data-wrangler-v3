"""
gen_scout_tickets.py — synthesize text-layer well scout ticket PDFs for testing the
bulk loader / field-review screen without OCR.

Each ticket carries a real text layer and GRID-bordered tables so pdfplumber's
extract_text()/extract_tables() recover them directly. Section headers use the exact
signature words the loader's rows_of()/_find_col() look for; the Well Header uses
colon-suffixed labels so _header() maps dv_well. Casing ODs are intentionally written
as fractions (13-3/8") to exercise the review screen's OD recovery.
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

S = getSampleStyleSheet()
H = ParagraphStyle("sec", parent=S["Heading3"], textColor=colors.HexColor("#2b6b4f"),
                   spaceBefore=10, spaceAfter=4)
TITLE = ParagraphStyle("t", parent=S["Title"], fontSize=17, textColor=colors.HexColor("#333333"))
SUB = ParagraphStyle("s", parent=S["Normal"], fontSize=9, textColor=colors.HexColor("#777777"))


def _grid(data, widths=None, header=True):
    t = Table(data, colWidths=widths, hAlign="LEFT")
    style = [("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
             ("FONTSIZE", (0, 0), (-1, -1), 8),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
             ("LEFTPADDING", (0, 0), (-1, -1), 5)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f0")),
                  ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def build(path, w):
    doc = SimpleDocTemplate(path, pagesize=letter, topMargin=0.6 * inch,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    story = [Paragraph("WELL SCOUT TICKET", TITLE),
             Paragraph(f"DataView &middot; {w['operator']} &middot; {w['status']}", SUB),
             Spacer(1, 8)]

    # ---- Well Header (colon labels -> _header maps these to dv_well) ----
    story.append(Paragraph("Well Header", H))
    hdr = [["API:", w["api"], "Well Name:", w["well_name"]],
           ["Well Type:", w["well_type"], "Status:", w["status"]],
           ["Operator:", w["operator"], "Field:", w["field"]],
           ["County:", w["county"], "State:", w["state"]],
           ["Spud Date:", w["spud"], "Completion Date:", w["comp"]],
           ["Total Depth MD:", w["td"], "KB Elevation:", w["kb"]],
           ["UWI:", w["uwi"], "Surface Location:", w["loc"]]]
    story.append(_grid(hdr, widths=[1.15 * inch, 1.9 * inch, 1.35 * inch, 2.0 * inch], header=False))

    # ---- Formation Tops ----
    story.append(Paragraph("Stratigraphy &mdash; Formation Tops", H))
    ft = [["Formation", "Top MD (ft)", "Base MD (ft)", "Net Pay (ft)", "Fluid"]] + w["tops"]
    story.append(_grid(ft, widths=[1.7 * inch, 1.2 * inch, 1.2 * inch, 1.1 * inch, 1.1 * inch]))

    # ---- Casing (fractional OD on purpose) ----
    story.append(Paragraph("Casing &mdash; Cementing Record", H))
    cs = [["Casing String", "OD", "Weight (lb/ft)", "Grade", "Shoe Depth (ft)"]] + w["casing"]
    story.append(_grid(cs, widths=[1.7 * inch, 1.1 * inch, 1.3 * inch, 1.0 * inch, 1.4 * inch]))

    # ---- Directional Survey ----
    story.append(Paragraph("Directional Survey &mdash; first 10 stations", H))
    sv = [["MD (ft)", "Inc", "Azi", "TVD (ft)", "N/S (ft)", "E/W (ft)", "DLS"]] + w["survey"]
    story.append(_grid(sv, widths=[0.95 * inch] * 7))

    # ---- DST ----
    story.append(Paragraph("DST &mdash; Drill Stem Tests", H))
    dst = [["Test Date", "Type", "Top MD (ft)", "Base MD (ft)", "Result",
            "Max Oil (bbl/d)", "Max Gas (Mcf/d)", "API Gravity"], w["dst"]]
    story.append(_grid(dst, widths=[0.95 * inch] * 8))

    doc.build(story)
    return path


def survey(base_az, kop=1500, td=9500):
    rows, md, tvd, ns, ew = [], 250, 250, 0, 0
    inc = 0.0
    for _ in range(10):
        inc = min(90.0, inc + (7.5 if md > kop else 1.0))
        rows.append([f"{md:,}", f"{inc:.2f}", f"{base_az:.2f}", f"{tvd:,}",
                     str(ns), str(ew), f"{(inc/ (md/1000)):.2f}"[:4]])
        step = 260
        md += step
        tvd += int(step * max(0.15, (90 - inc) / 90))
        ns += int(step * 0.6); ew += int(step * 0.35)
    return rows


WELLS = [
    dict(api="42317000120000", uwi="US42317000120000", well_name="STATE ALPHA 12H",
         well_type="HORIZONTAL", status="ACTIVE", operator="Pioneer Natural Resources",
         field="Spraberry Trend", county="Midland", state="Texas",
         spud="2019-05-14", comp="2019-09-02", td="19,850 ft", kb="2,845 ft",
         loc="31.998400N 102.077500W",
         tops=[["Spraberry", "6,120", "7,050", "\u2014", "\u2014"],
               ["Wolfcamp A", "7,540", "8,120", "62.4", "OIL"],
               ["Wolfcamp B", "8,340", "9,010", "88.1", "OIL"]],
         casing=[["Conductor", "20", "94", "K-55", "280"],
                 ["Surface", "13-3/8\"", "54.5", "K-55", "3,050"],
                 ["Intermediate", "9-5/8\"", "47", "L-80", "10,400"],
                 ["Production", "5-1/2\"", "20", "P-110", "19,600"]],
         survey=survey(311.5),
         dst=["2019-08-21", "DST", "8,340", "8,760", "OIL", "1,240", "880", "41.2"]),
    dict(api="42003000080000", uwi="US42003000080000", well_name="STATE BRAVO 8H",
         well_type="HORIZONTAL", status="COMPLETED", operator="Chevron U.S.A.",
         field="Wolfcamp Play", county="Andrews", state="Texas",
         spud="2021-02-03", comp="2021-06-19", td="21,120 ft", kb="3,180 ft",
         loc="32.305100N 102.640300W",
         tops=[["Clearfork", "5,880", "6,640", "\u2014", "\u2014"],
               ["Spraberry", "6,640", "7,720", "\u2014", "\u2014"],
               ["Wolfcamp A", "7,980", "8,910", "104.0", "OIL"],
               ["Wolfcamp B", "8,910", "9,540", "52.2", "GAS"]],
         casing=[["Conductor", "20", "94", "K-55", "300"],
                 ["Surface", "13-3/8\"", "54.5", "J-55", "3,200"],
                 ["Intermediate", "9-5/8\"", "43.5", "L-80", "10,900"],
                 ["Production", "5-1/2\"", "23", "P-110", "20,850"]],
         survey=survey(158.0),
         dst=["2021-05-30", "DST", "8,910", "9,320", "GAS", "310", "4,180", "\u2014"]),
]

if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for i, w in enumerate(WELLS, 1):
        p = f"{out}/scout_ticket_text_{i}_{w['well_name'].replace(' ', '_')}.pdf"
        build(p, w)
        print("wrote", p)
