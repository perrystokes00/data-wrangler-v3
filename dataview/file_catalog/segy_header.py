"""
segy_header.py — dependency-free SEG-Y header reader for cataloging.
====================================================================
Reads exactly what the catalog needs from a SEG-Y file — textual header,
sample interval, samples/trace, data format, trace count, 2D/3D, and the
CDP coordinate bounding box — using only the standard library. No segyio.

Why hand-rolled: SEG-Y (rev 1/2) is a rigid, documented layout — a 3200-byte
EBCDIC textual header, a 400-byte binary header at fixed offsets, then
240-byte trace headers. Cataloging never needs the trace *samples*, so we
read header bytes only and never touch the data. That makes this both
dependency-free and faster than segyio, which indexes the whole file on open
to give trace access we don't use here.

Byte positions follow the SEG-Y rev 1 standard (the same defaults segyio
uses). Real-world files sometimes relocate CDP-X/Y or inline/crossline into
vendor-specific trace-header bytes; when that happens these standard offsets
return zeros/garbage for geometry — the same blind spot segyio has without a
custom header map. Everything is best-effort and never raises: on any problem
a field is left None and a note is recorded.

CLI:  python segy_header.py FILE [FILE ...]
"""
from __future__ import annotations

import os
import struct
from typing import Optional

# ── constants ────────────────────────────────────────────────────────────────
TEXT_HDR = 3200          # textual header bytes (40 lines x 80 cols, EBCDIC)
BIN_HDR = 400            # binary header bytes
TRACE_HDR = 240          # per-trace header bytes
EXT_HDR = 3200           # each extended textual header

# data sample format code -> (description, bytes per sample)
_FORMAT = {
    1: ("4-byte IBM float", 4),
    2: ("4-byte signed int", 4),
    3: ("2-byte signed int", 2),
    4: ("4-byte fixed-point w/ gain (obsolete)", 4),
    5: ("4-byte IEEE float", 4),
    6: ("8-byte IEEE double", 8),
    7: ("3-byte signed int", 3),
    8: ("1-byte signed int", 1),
    9: ("8-byte signed int", 8),
    10: ("4-byte unsigned int", 4),
    11: ("2-byte unsigned int", 2),
    12: ("8-byte unsigned int", 8),
    15: ("3-byte unsigned int", 3),
    16: ("1-byte unsigned int", 1),
}

_MEAS = {1: "meters", 2: "feet"}


def _printable_ratio(s: str) -> float:
    if not s:
        return 0.0
    good = sum(1 for c in s if c == "\n" or 32 <= ord(c) < 127)
    return good / len(s)


def _decode_textual(raw: bytes) -> str:
    """Decode the 3200-byte textual header, trying EBCDIC then ASCII, and
    lay it out as 40 lines of 80 characters (the SEG-Y card-image format)."""
    best = ""
    for enc in ("cp037", "ascii", "latin-1"):
        try:
            txt = raw.decode(enc, errors="replace")
        except Exception:
            continue
        if _printable_ratio(txt) > _printable_ratio(best):
            best = txt
        if _printable_ratio(best) > 0.95:
            break
    # reflow into 40x80 card image
    lines = [best[i:i + 80].rstrip() for i in range(0, min(len(best), 3200), 80)]
    return "\n".join(lines).rstrip()


def _u16(buf, off, big=True):
    return struct.unpack_from(">H" if big else "<H", buf, off)[0]


def _s16(buf, off, big=True):
    return struct.unpack_from(">h" if big else "<h", buf, off)[0]


def _s32(buf, off, big=True):
    return struct.unpack_from(">i" if big else "<i", buf, off)[0]


def _apply_scalar(value: int, scalar: int) -> float:
    """SEG-Y coordinate scalar (trace bytes 71-72): negative => divide,
    positive => multiply, zero => as-is."""
    if scalar > 0:
        return float(value) * scalar
    if scalar < 0:
        return float(value) / abs(scalar)
    return float(value)


def read_segy_header(path: str, *, max_geom_traces: int = 300) -> dict:
    """Catalog a SEG-Y file from its headers alone. Returns a dict of fields
    plus 'notes' (list of caveats) and 'ok' (bool). Never raises."""
    out: dict = {
        "ok": False, "path": path, "notes": [],
        "byte_order": None, "segy_revision": None,
        "sample_interval_us": None, "n_samples": None,
        "trace_length_ms": None,
        "format_code": None, "format_desc": None, "bytes_per_sample": None,
        "measurement_system": None,
        "n_traces": None, "n_ext_text_headers": None,
        "dims": None,
        "inline_range": None, "crossline_range": None,
        "cdp_x_range": None, "cdp_y_range": None,
        "cdp_points": [],
        "n_geom_traces_sampled": 0,
        "textual_header": "",
        "_data_start": None, "_bytes_per_trace": None, "_big_endian": None,
    }
    try:
        fsize = os.path.getsize(path)
    except OSError as e:
        out["notes"].append(f"stat failed: {e}")
        return out
    if fsize < TEXT_HDR + BIN_HDR:
        out["notes"].append(f"file too small for SEG-Y headers ({fsize} bytes)")
        return out

    try:
        with open(path, "rb") as f:
            head = f.read(TEXT_HDR + BIN_HDR)          # 3600 bytes
            out["textual_header"] = _decode_textual(head[:TEXT_HDR])
            binh = head[TEXT_HDR:TEXT_HDR + BIN_HDR]    # 400 bytes

            # endianness: trust big-endian (the standard) unless its format
            # code is nonsense and the byte-swapped one is valid
            big = True
            fmt_be = _s16(binh, 24, True)
            if fmt_be not in _FORMAT:
                fmt_le = _s16(binh, 24, False)
                if fmt_le in _FORMAT:
                    big = False
                    out["notes"].append("little-endian detected (non-standard)")
            out["byte_order"] = "big" if big else "little"

            samp_int = _u16(binh, 16, big)              # microseconds
            n_samp = _u16(binh, 20, big)
            fmt = _s16(binh, 24, big)
            meas = _s16(binh, 54, big)
            rev = _s16(binh, 300, big)
            n_ext = _s16(binh, 304, big)

            desc, bps = _FORMAT.get(fmt, (f"unknown code {fmt}", 4))
            if fmt not in _FORMAT:
                out["notes"].append(f"unrecognized format code {fmt}; assuming 4 bytes/sample")

            out["sample_interval_us"] = samp_int or None
            out["n_samples"] = n_samp or None
            out["format_code"] = fmt
            out["format_desc"] = desc
            out["bytes_per_sample"] = bps
            out["measurement_system"] = _MEAS.get(meas, f"code {meas}")
            out["segy_revision"] = rev
            out["n_ext_text_headers"] = n_ext
            if samp_int and n_samp:
                out["trace_length_ms"] = round(n_samp * samp_int / 1000.0, 3)

            # extended textual headers sit between binary header and trace 1
            ext = n_ext if (n_ext and n_ext > 0) else 0
            if n_ext == -1:
                out["notes"].append("variable extended headers (-1); trace count approximate")
            data_start = TEXT_HDR + BIN_HDR + ext * EXT_HDR

            bytes_per_trace = TRACE_HDR + (n_samp * bps if n_samp else 0)
            out["_data_start"] = data_start
            out["_bytes_per_trace"] = bytes_per_trace
            out["_big_endian"] = big
            if bytes_per_trace > TRACE_HDR and fsize > data_start:
                n_traces = (fsize - data_start) // bytes_per_trace
                out["n_traces"] = int(n_traces)
            else:
                n_traces = 0
                out["notes"].append("could not compute trace count "
                                    "(missing samples/trace or short file)")

            # ── geometry sample: read only the 240-byte trace headers ──
            if n_traces > 0:
                step = max(1, n_traces // max(1, max_geom_traces))
                xs, ys, ils, xls = [], [], [], []
                sampled = 0
                idx = 0
                while idx < n_traces and sampled < max_geom_traces:
                    toff = data_start + idx * bytes_per_trace
                    f.seek(toff)
                    th = f.read(TRACE_HDR)
                    if len(th) < TRACE_HDR:
                        break
                    scalar = _s16(th, 70, big)           # bytes 71-72
                    cx = _s32(th, 180, big)              # bytes 181-184
                    cy = _s32(th, 184, big)              # bytes 185-188
                    il = _s32(th, 188, big)              # bytes 189-192
                    xl = _s32(th, 192, big)              # bytes 193-196
                    xs.append(_apply_scalar(cx, scalar))
                    ys.append(_apply_scalar(cy, scalar))
                    ils.append(il)
                    xls.append(xl)
                    sampled += 1
                    idx += step
                out["n_geom_traces_sampled"] = sampled

                def _rng(v):
                    nz = [x for x in v if x != 0]
                    src = nz or v
                    return (min(src), max(src)) if src else None

                out["inline_range"] = _rng(ils)
                out["crossline_range"] = _rng(xls)
                cxr = _rng(xs)
                cyr = _rng(ys)
                out["cdp_x_range"] = cxr
                out["cdp_y_range"] = cyr
                out["cdp_points"] = list(zip(xs, ys))   # scalar already applied

                n_il = len(set(ils))
                n_xl = len(set(xls))
                if n_il > 1 and n_xl > 1:
                    out["dims"] = "3D"
                elif (cxr and cxr[0] != cxr[1]) or (cyr and cyr[0] != cyr[1]):
                    out["dims"] = "2D"
                else:
                    out["dims"] = "2D?"
                    out["notes"].append("geometry flat in standard header bytes "
                                        "— file may use vendor-specific positions")

            out["ok"] = out["sample_interval_us"] is not None
    except Exception as e:
        out["notes"].append(f"{type(e).__name__}: {e}")
    return out


def to_catalog_fields(h: dict) -> dict:
    """Map the raw header dict onto the same field names the light extractor
    uses for SEG-Y, so this can drop into _extract_fields in place of segyio."""
    cx = h.get("cdp_x_range") or (None, None)
    cy = h.get("cdp_y_range") or (None, None)
    return {
        "n_traces": h.get("n_traces"),
        "sample_interval": h.get("sample_interval_us"),
        "n_samples": h.get("n_samples"),
        "seismic_dims": h.get("dims"),               # "2D" / "3D"
        "sample_format": h.get("format_desc"),
        "measurement_system": h.get("measurement_system"),
        "cdp_x_min": cx[0], "cdp_x_max": cx[1],
        "cdp_y_min": cy[0], "cdp_y_max": cy[1],
        "inline_range": h.get("inline_range"),
        "crossline_range": h.get("crossline_range"),
        "textual_header": h.get("textual_header"),
        "segy_notes": "; ".join(h.get("notes") or []),
    }


def sample_trace_rows(path: str, limit: int = 100) -> list:
    """First `limit` trace headers as preview rows:
        [{Trace, CDP, CDP_X, CDP_Y, Offset}, ...]
    Coordinate scalar (trace bytes 71-72) is applied to CDP-X/Y. Dependency-free
    replacement for the segyio header-preview loop. Never raises."""
    rows: list = []
    h = read_segy_header(path, max_geom_traces=1)
    if not h.get("ok"):
        return rows
    big = bool(h.get("_big_endian"))
    ds = h.get("_data_start")
    bpt = h.get("_bytes_per_trace")
    nt = h.get("n_traces") or 0
    if not ds or not bpt or nt <= 0:
        return rows
    n = min(int(nt), int(limit))
    try:
        with open(path, "rb") as f:
            for i in range(n):
                f.seek(ds + i * bpt)
                th = f.read(TRACE_HDR)
                if len(th) < TRACE_HDR:
                    break
                scalar = _s16(th, 70, big)              # bytes 71-72
                rows.append({
                    "Trace": i + 1,
                    "CDP":   _s32(th, 20, big),         # bytes 21-24
                    "CDP_X": _apply_scalar(_s32(th, 180, big), scalar),
                    "CDP_Y": _apply_scalar(_s32(th, 184, big), scalar),
                    "Offset": _s32(th, 36, big),        # bytes 37-40
                })
    except Exception:
        pass
    return rows


def _fmt_pair(p):
    return f"{p[0]:,} … {p[1]:,}" if p else "—"


def main(argv=None):
    import sys
    paths = argv if argv is not None else sys.argv[1:]
    if not paths:
        print("usage: python segy_header.py FILE [FILE ...]")
        return
    for p in paths:
        h = read_segy_header(p)
        print("=" * 72)
        print(os.path.basename(p))
        print("-" * 72)
        print(f"  ok                : {h['ok']}   ({h['byte_order']}-endian, "
              f"rev {h['segy_revision']})")
        print(f"  sample interval   : {h['sample_interval_us']} µs")
        print(f"  samples / trace   : {h['n_samples']}  "
              f"(trace length {h['trace_length_ms']} ms)")
        print(f"  data format       : {h['format_code']} — {h['format_desc']}")
        print(f"  measurement system: {h['measurement_system']}")
        print(f"  trace count       : {h['n_traces']:,}" if h['n_traces']
              else "  trace count       : —")
        print(f"  dimensionality    : {h['dims']}  "
              f"(sampled {h['n_geom_traces_sampled']} trace headers)")
        print(f"  inline range      : {_fmt_pair(h['inline_range'])}")
        print(f"  crossline range   : {_fmt_pair(h['crossline_range'])}")
        print(f"  CDP-X range       : {_fmt_pair(h['cdp_x_range'])}")
        print(f"  CDP-Y range       : {_fmt_pair(h['cdp_y_range'])}")
        if h["notes"]:
            print(f"  notes             : {'; '.join(h['notes'])}")
        print("  textual header (first 6 lines):")
        for line in (h["textual_header"] or "").splitlines()[:6]:
            print(f"    | {line}")


if __name__ == "__main__":
    main()
