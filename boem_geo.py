"""
boem_geo.py — BOEM OCS protraction-area polygons for spatially constraining
Gulf of America (GOM) wells.

This is the offshore analog of us_geo.py. Instead of state/county boundaries it
loads BOEM protraction areas from a GeoJSON file and exposes, per area:

    bbox(area)        -> (min_lat, min_lon, max_lat, max_lon)   [matches us_geo]
    geometry(area)    -> the raw GeoJSON geometry dict
    contains(area,..) -> point-in-polygon test (lat, lon)
    feature(area)     -> the full GeoJSON feature
    area_codes()      -> sorted list of area identifiers
    feature_collection() -> a FeatureCollection of all areas (for map overlay)

GeoJSON is assumed to be in WGS84 / EPSG:4326 (lon, lat) — the GeoJSON spec
default — so there is NO reprojection step (the big advantage over a shapefile).

Default file location (override with path=):
    assets/geo/gom_protraction.geojson   (alongside this module)

The protraction-area identifier field is auto-detected from a list of common
BOEM property names; override with set_code_field("YOUR_FIELD") if needed.
Run `python boem_geo.py <file.geojson>` to print the detected field + areas.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DEFAULT_REL = Path("assets/geo/gom_protraction.geojson")

# Candidate property names that hold the protraction-area identifier, in
# priority order. BOEM / MMS exports vary, so we probe several. The matched
# value is compared against the well's bottom_area_code, normalized (upper +
# stripped), so "MC" matches "mc " etc.
_CODE_FIELD_CANDIDATES = [
    "AREA_CODE", "AREACODE", "AREA_SYM", "AREASYM", "AREA_ABBR",
    "PROT_CODE", "PROTRACT", "PROT_NUMBER", "PROTNUM", "PROT_APRVD",
    "MMS_AREA", "MMS_AREA_C", "AC_LAB", "BLOCK_LAB", "AREA_ABV",
    "TEXT_LABEL", "LABEL", "NAME", "AREA_NAME", "REGION",
]

# Optional explicit override set by the host app.
_CODE_FIELD_OVERRIDE: str | None = None


def set_code_field(field_name: str | None) -> None:
    """Force a specific GeoJSON property to be used as the area identifier."""
    global _CODE_FIELD_OVERRIDE
    _CODE_FIELD_OVERRIDE = field_name
    _index.cache_clear()


def _resolve_path(path=None) -> Path:
    if path:
        return Path(path)
    return Path(__file__).parent / _DEFAULT_REL


@lru_cache(maxsize=8)
def _load(path_str: str | None) -> dict:
    p = _resolve_path(path_str)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def available(path=None) -> bool:
    """True if the GeoJSON exists and has at least one feature."""
    gj = _load(str(path) if path else None)
    return bool(gj.get("features"))


def _detect_code_field(features) -> str | None:
    if _CODE_FIELD_OVERRIDE:
        return _CODE_FIELD_OVERRIDE
    if not features:
        return None
    props = features[0].get("properties", {}) or {}
    lower = {k.lower(): k for k in props.keys()}
    for cand in _CODE_FIELD_CANDIDATES:
        if cand.lower() in lower:
            return lower[cand.lower()]
    # Fallback: first non-empty string property.
    for k, v in props.items():
        if isinstance(v, str) and v.strip():
            return k
    return None


def _norm(code) -> str:
    return str(code).strip().upper()


@lru_cache(maxsize=8)
def _index(path_str: str | None):
    """
    Build {normalized_area_code: feature} plus the detected code field.
    Returns (field_name, {code: feature}).
    """
    gj = _load(path_str)
    feats = gj.get("features", []) or []
    field = _detect_code_field(feats)
    idx: dict[str, dict] = {}
    if field:
        for f in feats:
            props = f.get("properties", {}) or {}
            val = props.get(field)
            if val is None or str(val).strip() == "":
                continue
            idx[_norm(val)] = f
    return field, idx


def code_field(path=None) -> str | None:
    """The GeoJSON property currently used as the area identifier."""
    return _index(str(path) if path else None)[0]


def area_codes(path=None) -> list[str]:
    """Sorted list of normalized protraction-area identifiers in the file."""
    return sorted(_index(str(path) if path else None)[1].keys())


def feature(area, path=None) -> dict | None:
    """The full GeoJSON feature for an area identifier (or None)."""
    return _index(str(path) if path else None)[1].get(_norm(area))


def geometry(area, path=None) -> dict | None:
    """The GeoJSON geometry dict for an area (or None)."""
    f = feature(area, path)
    return f.get("geometry") if f else None


def _iter_rings(geom):
    """Yield each coordinate ring (list of [lon, lat]) for Polygon/MultiPolygon."""
    if not geom:
        return
    gtype = geom.get("type")
    coords = geom.get("coordinates", [])
    if gtype == "Polygon":
        for ring in coords:
            yield ring
    elif gtype == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                yield ring


def bbox(area, path=None):
    """
    (min_lat, min_lon, max_lat, max_lon) for an area — same tuple order us_geo
    returns, so the caller's BETWEEN clause is identical. None if not found.
    """
    geom = geometry(area, path)
    if not geom:
        return None
    mnla = mnlo = float("inf")
    mxla = mxlo = float("-inf")
    found = False
    for ring in _iter_rings(geom):
        for pt in ring:
            lon, lat = pt[0], pt[1]
            found = True
            if lat < mnla: mnla = lat
            if lat > mxla: mxla = lat
            if lon < mnlo: mnlo = lon
            if lon > mxlo: mxlo = lon
    if not found:
        return None
    return (mnla, mnlo, mxla, mxlo)


def contains(area, lat, lon, path=None) -> bool:
    """
    Point-in-polygon test (ray casting) against an area's geometry. Handles
    Polygon and MultiPolygon. Outer/holes aren't distinguished here — adequate
    for the convex-ish protraction areas; bbox pre-filtering does the heavy
    lifting and this refines the edges.
    """
    geom = geometry(area, path)
    if not geom:
        return False
    inside = False
    for ring in _iter_rings(geom):
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if ((yi > lat) != (yj > lat)) and \
               (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
                inside = not inside
            j = i
    return inside


def feature_collection(path=None) -> dict:
    """All areas as a FeatureCollection (for drawing the overlay on the map)."""
    _, idx = _index(str(path) if path else None)
    return {"type": "FeatureCollection", "features": list(idx.values())}


def overall_bbox(path=None):
    """
    (min_lat, min_lon, max_lat, max_lon) covering ALL protraction areas — i.e.
    the whole Gulf footprint. Used to constrain to the Gulf when no specific
    protraction area is chosen. None if the file is empty.
    """
    codes = area_codes(path)
    if not codes:
        return None
    mnla = mnlo = float("inf")
    mxla = mxlo = float("-inf")
    for c in codes:
        bb = bbox(c, path)
        if not bb:
            continue
        a, b, cc, d = bb
        mnla = min(mnla, a); mnlo = min(mnlo, b)
        mxla = max(mxla, cc); mxlo = max(mxlo, d)
    if mnla == float("inf"):
        return None
    return (mnla, mnlo, mxla, mxlo)


if __name__ == "__main__":
    import sys
    _p = sys.argv[1] if len(sys.argv) > 1 else None
    if not available(_p):
        print(f"No GeoJSON found / empty at: {_resolve_path(_p)}")
        sys.exit(1)
    _field = code_field(_p)
    _codes = area_codes(_p)
    print(f"File:        {_resolve_path(_p)}")
    print(f"Code field:  {_field!r}  (override with set_code_field if wrong)")
    print(f"Areas ({len(_codes)}): {', '.join(_codes[:40])}"
          + (" ..." if len(_codes) > 40 else ""))
    if _codes:
        _bb = bbox(_codes[0], _p)
        print(f"Sample bbox  {_codes[0]} -> (min_lat,min_lon,max_lat,max_lon) = {_bb}")
