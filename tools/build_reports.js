const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  PageBreak, Header, Footer, PageNumber, TabStopType,
} = require("docx");

const data = JSON.parse(fs.readFileSync("/home/claude/report_data.json", "utf8"));
const OUT = "/home/claude/fixtures";

const NAVY = "1F3864";
const GREY = "F2F2F2";
const CONTENT = 9360;            // US Letter minus 1" margins, in DXA

const txt = (t, o = {}) => new TextRun({ text: String(t ?? ""), font: "Calibri", ...o });
const para = (t, o = {}) => new Paragraph({ children: [txt(t, o.run || {})], ...o.p });

function cell(t, { bold = false, head = false, width, align } = {}) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: head ? { type: ShadingType.CLEAR, fill: NAVY } : undefined,
    margins: { top: 60, bottom: 60, left: 80, right: 80 },
    children: [new Paragraph({
      alignment: align,
      children: [txt(t, { bold: bold || head, color: head ? "FFFFFF" : undefined, size: 18 })],
    })],
  });
}

function table(headers, rows, widths) {
  const trs = [];
  if (headers) {
    trs.push(new TableRow({
      tableHeader: true,
      children: headers.map((h, i) => cell(h, { head: true, width: widths[i] })),
    }));
  }
  rows.forEach((r, ri) => {
    trs.push(new TableRow({
      children: r.map((v, i) => new TableCell({
        width: { size: widths[i], type: WidthType.DXA },
        shading: ri % 2 ? { type: ShadingType.CLEAR, fill: GREY } : undefined,
        margins: { top: 50, bottom: 50, left: 80, right: 80 },
        children: [new Paragraph({ children: [txt(v, { size: 18 })] })],
      })),
    }));
  });
  return new Table({ columnWidths: widths, rows: trs, width: { size: CONTENT, type: WidthType.DXA } });
}

// two-column "label: value" spec table
function specTable(pairs) {
  const w = [2200, 2480, 2200, 2480];
  const rows = [];
  for (let i = 0; i < pairs.length; i += 2) {
    const a = pairs[i], b = pairs[i + 1] || ["", ""];
    rows.push(new TableRow({
      children: [
        cell(a[0], { bold: true, width: w[0] }), cell(a[1], { width: w[1] }),
        cell(b[0], { bold: true, width: w[2] }), cell(b[1], { width: w[3] }),
      ],
    }));
  }
  return new Table({ columnWidths: w, rows, width: { size: CONTENT, type: WidthType.DXA } });
}

function h1(t) {
  return new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 280, after: 140 },
    children: [txt(t, { bold: true, color: NAVY, size: 26 })] });
}
function h2(t) {
  return new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 200, after: 100 },
    children: [txt(t, { bold: true, color: NAVY, size: 22 })] });
}

function buildDoc(uwi, d) {
  const h = d.hdr;
  const api = uwi.replace(/-/g, "");
  const kids = [];

  // title block
  kids.push(new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 60 },
    children: [txt("FINAL WELL REPORT", { bold: true, size: 40, color: NAVY })],
  }));
  kids.push(new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 40 },
    children: [txt(h.WELL_NAME.trim(), { bold: true, size: 30 })],
  }));
  kids.push(new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 300 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: NAVY, space: 8 } },
    children: [txt(`${h.OPERATOR}  ·  ${h.FIELD_NAME}  ·  UWI ${api}`, { size: 20, color: "666666" })],
  }));

  kids.push(h1("1. Well Summary"));
  kids.push(specTable([
    ["API / UWI", api], ["Well Name", h.WELL_NAME.trim()],
    ["Operator", h.OPERATOR], ["Licensee", h.LICENSEE],
    ["Well Class", h.WELL_CLASS], ["Status", `${h.STATUS} (${h.STATUS_TYPE})`],
    ["Field", h.FIELD_NAME], ["Formation at TD", h.FORMATION_AT_TD],
    ["County", h.COUNTY], ["State / Country", `${h.PROVINCE_STATE} / ${h.COUNTRY}`],
    ["Surface Latitude", h.SURFACE_LATITUDE], ["Surface Longitude", h.SURFACE_LONGITUDE],
    ["Spud Date", h.SPUD_DATE], ["Completion Date", h.COMPLETION_DATE],
    ["Driller's TD", `${h.DRILLERS_TD} ${h.DEPTH_UNITS}`], ["Depth Datum", h.DEPTH_DATUM],
    ["KB Elevation", `${h.KB_ELEV} ${h.DEPTH_UNITS}`], ["GL Elevation", `${h.GL_ELEV} ${h.DEPTH_UNITS}`],
  ]));

  kids.push(new Paragraph({ spacing: { before: 200 }, children: [txt(
    `The ${h.WELL_NAME.trim()} was spudded on ${h.SPUD_DATE} by ${h.OPERATOR} in the ` +
    `${h.FIELD_NAME}, ${h.COUNTY}, ${h.PROVINCE_STATE}. The well was drilled as a ` +
    `${String(h.WELL_CLASS).toLowerCase()} well to a driller's total depth of ${h.DRILLERS_TD} ` +
    `${h.DEPTH_UNITS} MD, bottoming in the ${h.FORMATION_AT_TD}. Completion operations concluded ` +
    `on ${h.COMPLETION_DATE}. The well is currently reported as ${h.STATUS}.`, { size: 20 }) ] }));

  // formation tops
  if (d.picks.length) {
    kids.push(h1("2. Stratigraphy — Formation Tops"));
    kids.push(para(`${d.picks.length} formation top(s) were interpreted from log and cuttings data.`,
      { run: { size: 20 } }));
    kids.push(new Paragraph({ spacing: { after: 100 }, children: [] }));
    kids.push(table(
      ["Strat Unit", "Strat Name Set", "Top MD (ft)", "Base MD (ft)", "Gross (ft)", "Interp Date", "By"],
      d.picks.map(p => [p.STRAT_UNIT_ID, p.STRAT_NAME_SET_ID, p.TOP_MD, p.BASE_MD,
        String(Number(p.BASE_MD) - Number(p.TOP_MD)), p.INTERP_DATE, p.INTERP_BY]),
      [1900, 1700, 1200, 1200, 1100, 1360, 900]));
  }

  // logs + curves
  if (d.logs.length) {
    kids.push(h1("3. Wireline / LWD Logging"));
    d.logs.forEach(l => {
      kids.push(h2(`${l.LOG_TYPE} — Run ${l.RUN_NO} (${l.LOG_ID})`));
      kids.push(specTable([
        ["Log Date", l.LOG_DATE], ["Log Type", l.LOG_TYPE],
        ["Top Depth", `${l.TOP_DEPTH} ft`], ["Base Depth", `${l.BASE_DEPTH} ft`],
        ["Interval Logged", `${Number(l.BASE_DEPTH) - Number(l.TOP_DEPTH)} ft`], ["Source", l.SOURCE],
      ]));
    });
    if (d.curves.length) {
      kids.push(new Paragraph({ spacing: { before: 160, after: 80 },
        children: [txt(`Curves recorded (${d.curves.length}):`, { bold: true, size: 20 })] }));
      kids.push(table(["Curve", "Unit", "Min Value", "Max Value"],
        d.curves.map(c => [c.CURVE_NAME, c.CURVE_UNIT, c.MIN_VALUE, c.MAX_VALUE]),
        [2340, 2340, 2340, 2340]));
    }
  }

  kids.push(new Paragraph({ children: [new PageBreak()] }));

  // core
  if (d.core.length) {
    kids.push(h1("4. Coring"));
    kids.push(table(["Core ID", "Type", "Top (ft)", "Base (ft)", "Cut (ft)", "Recovery %", "Formation"],
      d.core.map(c => [c.CORE_ID, c.CORE_TYPE, c.TOP_DEPTH, c.BASE_DEPTH,
        String(Number(c.BASE_DEPTH) - Number(c.TOP_DEPTH)), c.RECOVERY_PCT, c.FORMATION]),
      [2200, 1500, 1000, 1000, 900, 1100, 1660]));
    const c0 = d.core[0];
    kids.push(new Paragraph({ spacing: { before: 160 }, children: [txt(
      `A ${String(c0.CORE_TYPE).toLowerCase()} core was cut over the ${c0.TOP_DEPTH}–${c0.BASE_DEPTH} ft ` +
      `interval in the ${c0.FORMATION}, recovering ${c0.RECOVERY_PCT}% of the cut interval.`,
      { size: 20 })] }));
  }

  // survey
  if (d.srvy.length) {
    kids.push(h1("5. Directional Survey"));
    const last = d.srvy[d.srvy.length - 1];
    const maxInc = Math.max(...d.srvy.map(s => Number(s.INCLINATION) || 0)).toFixed(2);
    kids.push(para(`${d.srvy.length} survey stations were recorded to a final measured depth of ` +
      `${last.MD} ft (TVDSS ${last.TVDSS} ft). Maximum inclination reached ${maxInc}°.`,
      { run: { size: 20 } }));
    kids.push(new Paragraph({ spacing: { after: 100 }, children: [] }));
    kids.push(table(["Seq", "MD (ft)", "Inclination (°)", "Azimuth (°)", "TVDSS (ft)"],
      d.srvy.map(s => [s.SURVEY_SEQ_NO, s.MD, s.INCLINATION, s.AZIMUTH, s.TVDSS]),
      [1000, 2090, 2090, 2090, 2090]));
  }

  kids.push(h1("6. Conclusions"));
  const tops = d.picks.map(p => p.STRAT_UNIT_ID).join(", ");
  kids.push(para(
    `${h.WELL_NAME.trim()} reached a total depth of ${h.DRILLERS_TD} ${h.DEPTH_UNITS} in the ` +
    `${h.FORMATION_AT_TD}. ` + (tops ? `Formation tops were picked for ${tops}. ` : "") +
    (d.core.length ? `Core was recovered over ${d.core.length} interval(s). ` : "") +
    (d.logs.length ? `A ${d.logs[0].LOG_TYPE} log suite was acquired over ` +
      `${d.logs[0].TOP_DEPTH}–${d.logs[0].BASE_DEPTH} ft. ` : "") +
    `The well is reported ${h.STATUS} as of the date of this report.`, { run: { size: 20 } }));

  kids.push(new Paragraph({ spacing: { before: 400 }, children: [txt(
    "Data source: PPDM training dataset. This document is synthetic and generated for " +
    "software testing purposes only.", { italics: true, size: 16, color: "888888" })] }));

  return new Document({
    creator: h.OPERATOR, title: `Final Well Report — ${h.WELL_NAME.trim()}`,
    description: `Synthetic final well report for UWI ${api}`,
    sections: [{
      properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
      headers: { default: new Header({ children: [new Paragraph({
        alignment: AlignmentType.RIGHT,
        border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 4 } },
        children: [txt(`Final Well Report — ${h.WELL_NAME.trim()}  ·  UWI ${api}`, { size: 16, color: "888888" })],
      })] }) },
      footers: { default: new Footer({ children: [new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [txt(`${h.OPERATOR}  ·  Page `, { size: 16, color: "888888" }),
                   new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "888888" })],
      })] }) },
      children: kids,
    }],
  });
}

(async () => {
  for (const [uwi, d] of Object.entries(data)) {
    const doc = buildDoc(uwi, d);
    const buf = await Packer.toBuffer(doc);
    const name = `${OUT}/Final_Well_Report_${d.hdr.WELL_NAME.trim().replace(/\s+/g, "_")}.docx`;
    fs.writeFileSync(name, buf);
    console.log("  " + name.split("/").pop() + `: ${d.picks.length} picks, ${d.curves.length} curves, ${d.srvy.length} stations`);
  }
})();
