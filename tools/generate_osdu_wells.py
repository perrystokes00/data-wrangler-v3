"""
generate_osdu_wells.py
Generates 100 realistic OSDU Well master-data JSON files.
Covers Permian Basin, DJ Basin, Williston Basin, Gulf Coast, Appalachia.
Run: python generate_osdu_wells.py --out C:\WellData\OSDU
"""
import argparse, json, random, uuid
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

# ── Reference data ──────────────────────────────────────────────────────────

BASINS = [
    {
        "name": "Midland Basin",
        "state": "TX", "state_id": "TX", "country": "US",
        "county_pool": ["Midland","Martin","Upton","Glasscock","Reagan",
                        "Andrews","Ector","Loving","Winkler"],
        "lat_range": (31.4, 32.4), "lon_range": (-102.8, -101.2),
        "formations": ["Wolfcamp A","Wolfcamp B","Spraberry","Dean","Bone Spring"],
        "operators": ["Pioneer Natural Resources","Diamondback Energy",
                      "Permian Resources","Coterra Energy","Double Eagle Energy"],
        "api_prefix": "42",   # Texas
        "county_codes": {"Midland":"301","Martin":"317","Upton":"461",
                         "Glasscock":"173","Reagan":"383","Andrews":"003",
                         "Ector":"135","Loving":"301","Winkler":"495"},
        "water_depth": 0,
        "status_pool": ["Producing","Producing","Producing","Shut-in","TA"],
        "td_range": (9000, 18000), "spud_year_range": (2018, 2025),
    },
    {
        "name": "Delaware Basin",
        "state": "TX", "state_id": "TX", "country": "US",
        "county_pool": ["Reeves","Ward","Culberson","Pecos","Jeff Davis"],
        "lat_range": (30.5, 31.8), "lon_range": (-104.2, -102.5),
        "formations": ["Bone Spring","Wolfcamp","Second Bone Spring","Third Bone Spring"],
        "operators": ["Occidental Petroleum","Chevron","Devon Energy",
                      "ConocoPhillips","Centennial Resource Development"],
        "api_prefix": "42",
        "county_codes": {"Reeves":"389","Ward":"475","Culberson":"109",
                         "Pecos":"371","Jeff Davis":"243"},
        "water_depth": 0,
        "status_pool": ["Producing","Producing","Shut-in","TA","Producing"],
        "td_range": (10000, 20000), "spud_year_range": (2017, 2025),
    },
    {
        "name": "DJ Basin",
        "state": "CO", "state_id": "CO", "country": "US",
        "county_pool": ["Weld","Adams","Arapahoe","Boulder","Morgan"],
        "lat_range": (39.8, 40.9), "lon_range": (-105.0, -103.8),
        "formations": ["Niobrara B","Niobrara C","Codell","Niobrara A"],
        "operators": ["Civitas Resources","Extraction Oil & Gas",
                      "Noble Energy","Bonanza Creek","Whiting Petroleum"],
        "api_prefix": "05",   # Colorado
        "county_codes": {"Weld":"123","Adams":"001","Arapahoe":"005",
                         "Boulder":"013","Morgan":"087"},
        "water_depth": 0,
        "status_pool": ["Producing","Producing","Producing","Shut-in","TA"],
        "td_range": (6500, 9500), "spud_year_range": (2016, 2025),
    },
    {
        "name": "Williston Basin",
        "state": "ND", "state_id": "ND", "country": "US",
        "county_pool": ["McKenzie","Mountrail","Williams","Dunn","Burke"],
        "lat_range": (47.5, 48.8), "lon_range": (-104.0, -102.0),
        "formations": ["Bakken","Three Forks","Middle Bakken","Lower Bakken"],
        "operators": ["Continental Resources","Hess Corporation",
                      "Oasis Petroleum","Marathon Oil","Whiting Petroleum"],
        "api_prefix": "33",   # North Dakota
        "county_codes": {"McKenzie":"053","Mountrail":"061","Williams":"105",
                         "Dunn":"025","Burke":"013"},
        "water_depth": 0,
        "status_pool": ["Producing","Producing","Shut-in","Producing","TA"],
        "td_range": (9500, 12500), "spud_year_range": (2015, 2024),
    },
    {
        "name": "Gulf Coast",
        "state": "TX", "state_id": "TX", "country": "US",
        "county_pool": ["Webb","Zapata","LaSalle","Frio","Dimmit"],
        "lat_range": (27.5, 29.0), "lon_range": (-100.5, -98.5),
        "formations": ["Eagle Ford","Austin Chalk","Pearsall","Buda"],
        "operators": ["EOG Resources","Murphy Oil","SM Energy",
                      "Marathon Oil","BPX Energy"],
        "api_prefix": "42",
        "county_codes": {"Webb":"479","Zapata":"505","LaSalle":"283",
                         "Frio":"163","Dimmit":"127"},
        "water_depth": 0,
        "status_pool": ["Producing","Producing","Producing","Shut-in","Producing"],
        "td_range": (7000, 14000), "spud_year_range": (2014, 2024),
    },
]

WELL_SUFFIXES = ["1H","2H","3H","4H","A1H","B1H","C1H","01H","02H","1-H","2-H"]
LEGAL_DESCS   = [
    "SW/4 SE/4", "NE/4 NW/4", "NW/4 SW/4", "SE/4 NE/4",
    "S/2 NE/4",  "N/2 SW/4",  "E/2 NW/4",  "W/2 SE/4",
]
LEASEHOLDERS  = [
    "State of {state}", "Federal", "Smith Family Trust",
    "Johnson Ranch LLC", "Permian Land Co.", "Prairie Holdings",
    "Williston Land Trust", "{operator} Lease", "Heritage Resources",
]


def _api(basin: dict, county: str, seq: int) -> str:
    st  = basin["api_prefix"]
    cty = basin["county_codes"].get(county, "000")
    return f"{st}-{cty}-{seq:05d}-0000"


def _spud(basin: dict) -> date:
    y0, y1 = basin["spud_year_range"]
    year   = random.randint(y0, y1)
    doy    = random.randint(1, 365)
    return date(year, 1, 1) + timedelta(days=doy - 1)


def _drill_days() -> int:
    return random.randint(18, 65)


def make_well(seq: int, basin: dict, well_seq: int) -> dict:
    county   = random.choice(basin["county_pool"])
    operator = random.choice(basin["operators"])
    api      = _api(basin, county, 10000 + well_seq)
    uwi      = api.replace("-","")

    # Well name  e.g. "Johnson Ranch 12-34H"
    sec = random.randint(1, 36)
    twp = random.randint(1, 12)
    rng = random.randint(1, 15)
    suf = random.choice(WELL_SUFFIXES)
    legal = random.choice(LEGAL_DESCS)
    leaseholder = random.choice(LEASEHOLDERS).format(
        state=basin["state"], operator=operator.split()[0])
    well_name = f"{leaseholder.split()[0]} {sec}-{twp}{suf}"

    lat = round(random.uniform(*basin["lat_range"]), 6)
    lon = round(random.uniform(*basin["lon_range"]), 6)

    spud        = _spud(basin)
    drill_days  = _drill_days()
    completion  = spud + timedelta(days=drill_days + random.randint(15, 45))
    td          = random.randint(*basin["td_range"])
    formation   = random.choice(basin["formations"])
    status      = random.choice(basin["status_pool"])
    kb          = round(random.uniform(2500, 4200) if basin["state"]=="CO"
                        else random.uniform(2800, 3800), 1)

    return {
        "kind": "osdu:wks:master-data--Well:1.3.0",
        "acl": {
            "viewers": ["data.default.viewers@opendes.contoso.com"],
            "owners":  ["data.default.owners@opendes.contoso.com"],
        },
        "legal": {
            "legaltags": ["opendes-demo-legaltag"],
            "otherRelevantDataCountries": [basin["country"]],
        },
        "data": {
            "FacilityID":   api,
            "FacilityName": well_name,
            "FacilityNameAliases": [
                {"AliasName": api,      "AliasNameTypeID": "osdu:reference-data--AliasNameType:API14"},
                {"AliasName": uwi[:12], "AliasNameTypeID": "osdu:reference-data--AliasNameType:API12"},
                {"AliasName": well_name,"AliasNameTypeID": "osdu:reference-data--AliasNameType:CommonName"},
            ],
            "OperatorName": operator,
            "OperatorID":   f"osdu:master-data--Organisation:{operator.lower().replace(' ','-')}",
            "CountryID":    f"osdu:reference-data--GeopoliticalEntityType:Country:{basin['country']}",
            "StateProvinceID": f"osdu:reference-data--GeopoliticalEntityType:StateProvince:{basin['state']}",
            "County":       county,
            "WellStatus":   status,
            "WellStatusTypeID": f"osdu:reference-data--WellStatusType:{status.upper().replace('-','_')}",
            "SpudDate":     spud.isoformat(),
            "DrillingCompletion": completion.isoformat(),
            "InitialCompletionDate": (completion + timedelta(days=random.randint(20,60))).isoformat(),
            "OriginalOperator": operator,
            "Field":        basin["name"],
            "FormationAtTotalDepth": formation,
            "DrillersTotalDepth": td,
            "DepthUnit":    "ft",
            "WaterDepth":   0.0,
            "LegalDescription": legal,
            "Section":      sec,
            "Township":     twp,
            "Range":        rng,
            "SpatialLocation": {
                "AsIngestedCoordinates": {
                    "CoordinateReferenceSystemID":
                        "osdu:reference-data--CoordinateReferenceSystem:NAD83",
                    "FirstPoint": {
                        "Latitude":  lat,
                        "Longitude": lon,
                    },
                    "FeatureCollection": {
                        "type": "FeatureCollection",
                        "features": [{
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [lon, lat, kb],
                            },
                            "properties": {},
                        }],
                    },
                }
            },
            "WellBores": [{
                "WellboreID": f"osdu:master-data--Wellbore:{uwi}-WB01",
                "WellboreName": f"{well_name}-WB01",
                "VerticalMeasurement": {
                    "VerticalMeasurementID": "KB",
                    "VerticalMeasurement": kb,
                    "VerticalMeasurementUnit": "ft",
                },
            }],
            "GeoContexts": [
                {
                    "GeoPoliticalEntityID":
                        f"osdu:reference-data--GeopoliticalEntityType:Country:{basin['country']}",
                    "GeoTypeID": "osdu:reference-data--GeopoliticalEntityType:Country",
                },
                {
                    "GeoPoliticalEntityID":
                        f"osdu:reference-data--GeopoliticalEntityType:StateProvince:{basin['state']}",
                    "GeoTypeID": "osdu:reference-data--GeopoliticalEntityType:StateProvince",
                },
            ],
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="osdu_wells_100",
                    help="Output directory for JSON files")
    ap.add_argument("--count", type=int, default=100,
                    help="Number of wells to generate (default 100)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    n      = args.count
    # Distribute wells across basins proportionally
    counts = [n * w // 100 for w in [30, 20, 20, 15, 15]]
    counts[-1] += n - sum(counts)   # remainder to last basin

    written = 0
    for basin, basin_count in zip(BASINS, counts):
        for j in range(basin_count):
            well = make_well(written + 1, basin, written + 1)
            api  = well["data"]["FacilityID"].replace("-","_")
            fname = f"well_{api}.json"
            (out / fname).write_text(
                json.dumps(well, indent=2), encoding="utf-8")
            written += 1

    print(f"Generated {written} OSDU Well files → {out.resolve()}")
    print(f"Basin distribution:")
    for basin, c in zip(BASINS, counts):
        print(f"  {basin['name']:25s} {c} wells")


if __name__ == "__main__":
    main()
