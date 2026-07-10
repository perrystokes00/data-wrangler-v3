"""
us_geo.py — authoritative US state + county geography from a Census county
boundary GeoJSON. Replaces reliance on dv_well.province_state / .county,
which are sparse and inconsistently coded (Kansas has 514K wells with no
county; states appear as both "TX" and "Texas").

Drop the GeoJSON at assets/geo/us_counties.geojson (Census cartographic
boundary file: FeatureCollection of counties, each feature id = 5-digit
FIPS, properties.STATE = 2-digit state FIPS, properties.NAME = county name,
geometry = Polygon/MultiPolygon).

Public API (all cached after first load):
    states()                       -> ["AK","AL",...] state codes present
    state_name(code)               -> "Texas"
    state_labels()                 -> ["Alabama", ...] full names, sorted
    code_for_label(label)          -> "TX"
    counties(state_code)           -> ["Andrews", "Austin", ...] sorted
    bbox(state_code, county=None)  -> (min_lat,min_lon,max_lat,max_lon) | None
    geometry(state_code, county)   -> GeoJSON geometry dict | None

bbox is what drives BOTH the viewport (fit the map to it) and the well
filter (surface_latitude/longitude BETWEEN the bounds — works against
dv_well AND dataview_gom.well, since both carry those columns).
"""
import json
import os
from functools import lru_cache

# Default location; the loader also checks a couple of common spots.
_DEFAULT_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "assets", "geo", "us_counties.geojson"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "us_counties.geojson"),
]

# 2-digit state FIPS -> (USPS code, full name)
_FIPS = {
    "01": ("AL", "Alabama"), "02": ("AK", "Alaska"), "04": ("AZ", "Arizona"),
    "05": ("AR", "Arkansas"), "06": ("CA", "California"), "08": ("CO", "Colorado"),
    "09": ("CT", "Connecticut"), "10": ("DE", "Delaware"),
    "11": ("DC", "District of Columbia"), "12": ("FL", "Florida"),
    "13": ("GA", "Georgia"), "15": ("HI", "Hawaii"), "16": ("ID", "Idaho"),
    "17": ("IL", "Illinois"), "18": ("IN", "Indiana"), "19": ("IA", "Iowa"),
    "20": ("KS", "Kansas"), "21": ("KY", "Kentucky"), "22": ("LA", "Louisiana"),
    "23": ("ME", "Maine"), "24": ("MD", "Maryland"), "25": ("MA", "Massachusetts"),
    "26": ("MI", "Michigan"), "27": ("MN", "Minnesota"), "28": ("MS", "Mississippi"),
    "29": ("MO", "Missouri"), "30": ("MT", "Montana"), "31": ("NE", "Nebraska"),
    "32": ("NV", "Nevada"), "33": ("NH", "New Hampshire"), "34": ("NJ", "New Jersey"),
    "35": ("NM", "New Mexico"), "36": ("NY", "New York"),
    "37": ("NC", "North Carolina"), "38": ("ND", "North Dakota"), "39": ("OH", "Ohio"),
    "40": ("OK", "Oklahoma"), "41": ("OR", "Oregon"), "42": ("PA", "Pennsylvania"),
    "44": ("RI", "Rhode Island"), "45": ("SC", "South Carolina"),
    "46": ("SD", "South Dakota"), "47": ("TN", "Tennessee"), "48": ("TX", "Texas"),
    "49": ("UT", "Utah"), "50": ("VT", "Vermont"), "51": ("VA", "Virginia"),
    "53": ("WA", "Washington"), "54": ("WV", "West Virginia"),
    "55": ("WI", "Wisconsin"), "56": ("WY", "Wyoming"),
    "60": ("AS", "American Samoa"), "66": ("GU", "Guam"),
    "69": ("MP", "Northern Mariana Islands"), "72": ("PR", "Puerto Rico"),
    "78": ("VI", "U.S. Virgin Islands"),
}
_CODE_TO_FIPS = {code: fips for fips, (code, _n) in _FIPS.items()}
_CODE_TO_NAME = {code: name for _f, (code, name) in _FIPS.items()}
_NAME_TO_CODE = {name: code for _f, (code, name) in _FIPS.items()}


def _geom_bbox(geom):
    """(min_lon,min_lat,max_lon,max_lat) over a Polygon/MultiPolygon."""
    minx = miny = float("inf")
    maxx = maxy = float("-inf")

    def _ring(coords):
        nonlocal minx, miny, maxx, maxy
        for lon, lat in coords:
            if lon < minx: minx = lon
            if lon > maxx: maxx = lon
            if lat < miny: miny = lat
            if lat > maxy: maxy = lat

    t = geom.get("type")
    if t == "Polygon":
        for ring in geom["coordinates"]:
            _ring(ring)
    elif t == "MultiPolygon":
        for poly in geom["coordinates"]:
            for ring in poly:
                _ring(ring)
    if minx == float("inf"):
        return None
    return (minx, miny, maxx, maxy)


@lru_cache(maxsize=1)
def _load(path=None):
    """Returns dict: {state_code: {county_name: {'geom':..., 'bbox':(...)}}}."""
    src = path
    if src is None:
        src = next((p for p in _DEFAULT_PATHS if os.path.exists(p)), None)
    if not src or not os.path.exists(src):
        return {}
    with open(src, encoding="utf-8") as fh:
        gj = json.load(fh)
    out = {}
    for feat in gj.get("features", []):
        props = feat.get("properties", {})
        sfips = props.get("STATE")
        cname = props.get("NAME")
        geom = feat.get("geometry")
        if not (sfips and cname and geom):
            continue
        entry = _FIPS.get(sfips)
        if not entry:
            continue
        code = entry[0]
        bb = _geom_bbox(geom)            # (min_lon,min_lat,max_lon,max_lat)
        out.setdefault(code, {})[cname] = {"geom": geom, "bbox": bb}
    return out


def available(path=None):
    """True if the GeoJSON is present and parsed."""
    return bool(_load(path))


def states(path=None):
    return sorted(_load(path).keys())


def state_name(code):
    return _CODE_TO_NAME.get(code, code)


def state_labels(path=None):
    return sorted(state_name(c) for c in states(path))


def code_for_label(label):
    return _NAME_TO_CODE.get(label)


def counties(state_code, path=None):
    return sorted(_load(path).get(state_code, {}).keys())


def _to_latlon_bbox(lonlat_bbox):
    """(min_lon,min_lat,max_lon,max_lat) -> (min_lat,min_lon,max_lat,max_lon)."""
    if not lonlat_bbox:
        return None
    mnx, mny, mxx, mxy = lonlat_bbox
    return (mny, mnx, mxy, mxx)


def bbox(state_code, county=None, path=None):
    """Return (min_lat,min_lon,max_lat,max_lon) for a county, or the union
    over all counties for a whole state."""
    data = _load(path).get(state_code, {})
    if not data:
        return None
    if county:
        rec = data.get(county)
        return _to_latlon_bbox(rec["bbox"]) if rec else None
    # state-wide: union of county bboxes
    mnx = mny = float("inf")
    mxx = mxy = float("-inf")
    for rec in data.values():
        bb = rec["bbox"]
        if not bb:
            continue
        mnx = min(mnx, bb[0]); mny = min(mny, bb[1])
        mxx = max(mxx, bb[2]); mxy = max(mxy, bb[3])
    if mnx == float("inf"):
        return None
    return _to_latlon_bbox((mnx, mny, mxx, mxy))


def geometry(state_code, county, path=None):
    rec = _load(path).get(state_code, {}).get(county)
    return rec["geom"] if rec else None


def state_feature_collection(state_code, path=None):
    """GeoJSON FeatureCollection of every county in a state — ready to hand
    straight to folium.GeoJson for a boundary overlay."""
    data = _load(path).get(state_code, {})
    feats = [
        {"type": "Feature",
         "properties": {"state": state_code, "county": cname},
         "geometry": rec["geom"]}
        for cname, rec in data.items()
    ]
    return {"type": "FeatureCollection", "features": feats}


def county_feature(state_code, county, path=None):
    """Single-county GeoJSON Feature, or None."""
    geom = geometry(state_code, county, path)
    if not geom:
        return None
    return {"type": "Feature",
            "properties": {"state": state_code, "county": county},
            "geometry": geom}
