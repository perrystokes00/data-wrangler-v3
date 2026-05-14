"""
boem_area_codes.py
==================
BOEM OCS protraction area-code → friendly-name lookup.

Source: BOEM protraction-clip shapefile (protclip.dbf), 85 polygons
collapsed to 63 unique AREA_CODE values. Where a code spans multiple
protraction polygons (e.g. a base area plus an "Addition"), the
shortest PROT_NAME is taken as canonical, with a trailing " Area"
stripped for brevity.

Used by page_well_map.py to render the GOM Zoom-To dropdown with
human-readable names instead of bare 2-letter codes.

To refresh: re-run the DBF parse against an updated protclip.dbf.
"""

# AREA_CODE → canonical area name
BOEM_AREA_NAMES = {
    "AC": "Alaminos Canyon",
    "AM": "Amery Terrace",
    "AP": "Apalachicola",
    "AT": "Atwater Valley",
    "BA": "Brazos",
    "BM": "Bay Marchand",
    "BS": "Breton Sound",
    "CA": "Chandeleur",
    "CC": "Corpus Christi",
    "CE": "Campeche Escarpment",
    "CH": "Charlotte Harbor",
    "DC": "De Soto Canyon",
    "DD": "Destin Dome",
    "DT": "Dry Tortugas",
    "EB": "East Breaks",
    "EC": "East Cameron",
    "EI": "Eugene Island",
    "EL": "The Elbow",
    "EW": "Ewing Bank",
    "FM": "Florida Middle Ground",
    "FP": "Florida Plain",
    "GA": "Galveston",
    "GB": "Garden Banks",
    "GC": "Green Canyon",
    "GI": "Grand Isle",
    "GV": "Gainesville",
    "HE": "Henderson",
    "HH": "Howell Hook",
    "HI": "High Island",
    "KC": "Keathley Canyon",
    "KW": "Key West",
    "LL": "Lloyd Ridge",
    "LS": "Lund South",
    "LU": "Lund",
    "MA": "Miami",
    "MC": "Mississippi Canyon",
    "MI": "Matagorda Island",
    "MO": "Mobile",
    "MP": "Main Pass",
    "MU": "Mustang Island",
    "PB": "St. Petersburg",
    "PE": "Pensacola",
    "PI": "Port Isabel",
    "PL": "South Pelto",
    "PN": "North Padre Island",
    "PR": "Pulley Ridge",
    "PS": "South Padre Island",
    "RK": "Rankin",
    "SA": "Sabine Pass",
    "SE": "Sigsbee Escarpment",
    "SM": "South Marsh Island",
    "SP": "South Pass",
    "SS": "Ship Shoal",
    "ST": "South Timbalier",
    "SX": "Sabine Pass",
    "TP": "Tarpon Springs",
    "TV": "Tortugas Valley",
    "VK": "Viosca Knoll",
    "VN": "Vernon Basin",
    "VR": "Vermilion",
    "WC": "West Cameron",
    "WD": "West Delta",
    "WR": "Walker Ridge",
}


def area_name(code: str) -> str:
    """
    Return the friendly name for a BOEM area code, or the code itself
    (uppercased, stripped) if it isn't in the lookup. Never raises —
    an unknown code just falls through to itself.
    """
    if not code:
        return ""
    key = str(code).strip().upper()
    return BOEM_AREA_NAMES.get(key, key)
