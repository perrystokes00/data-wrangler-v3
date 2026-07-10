"""geo_keys.py — canonical key normalization for DataView loaders.

The loader MUST write dv_well.country / province_state / county using these
exact functions so the reference FKs resolve. county_id format: STATE_NAME
(uppercase, county/parish/borough suffix stripped); independent cities get a
_CITY suffix to stay distinct from a like-named county.
"""
_SUFFIXES = (" City and Borough", " Census Area", " Municipality",
             " Municipio", " Borough", " Parish", " County")

def split_county(name: str):
    """-> (core_name, county_type, is_independent_city)"""
    if name.endswith(" city"):
        return name[:-5], "City", True
    for s in _SUFFIXES:
        if name.endswith(s):
            return name[:-len(s)], s.strip(), False
    return name, "", False

def county_id(state_postal: str, county_name: str) -> str:
    core, _t, city = split_county(county_name)
    base = f"{state_postal.upper()}_{core.upper()}"
    return base + "_CITY" if city else base

def province_state_id(state_postal: str) -> str:
    return state_postal.upper()

def country_code(_country="United States") -> str:
    return "USA"
