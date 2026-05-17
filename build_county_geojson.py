"""
build_county_geojson.py — Build GeoJSON files by Texas petroleum region.

Usage:
    python build_county_geojson.py --region permian
    python build_county_geojson.py --region eagle-ford
    python build_county_geojson.py --region east-texas
    python build_county_geojson.py --region all-regions
    python build_county_geojson.py Andrews Ector Midland
    python build_county_geojson.py --list-regions
"""
import sys
import json
from build_well_geojson import build_geojson, DEFAULT_CONN
from sqlalchemy import create_engine

REGIONS = {
    "permian": {
        "label": "Permian Basin",
        "counties": [
            "Andrews", "Borden", "Crane", "Crockett", "Culberson",
            "Dawson", "Ector", "Gaines", "Glasscock", "Howard",
            "Irion", "Jeff Davis", "Loving", "Martin", "Midland",
            "Mitchell", "Nolan", "Pecos", "Reagan", "Reeves",
            "Schleicher", "Scurry", "Sterling", "Sutton", "Terrell",
            "Terry", "Upton", "Val Verde", "Ward", "Winkler",
            "Yoakum",
        ],
    },
    "eagle-ford": {
        "label": "Eagle Ford Shale",
        "counties": [
            "Atascosa", "Bee", "DeWitt", "Dimmit", "Frio",
            "Gonzales", "Karnes", "La Salle", "Lavaca", "Live Oak",
            "Maverick", "McMullen", "Medina", "Webb", "Wilson",
            "Zapata", "Zavala",
        ],
    },
    "east-texas": {
        "label": "East Texas",
        "counties": [
            "Anderson", "Camp", "Cass", "Cherokee", "Franklin",
            "Freestone", "Gregg", "Harrison", "Henderson", "Houston",
            "Leon", "Limestone", "Marion", "Morris", "Nacogdoches",
            "Navarro", "Panola", "Rusk", "Shelby", "Smith",
            "Titus", "Upshur", "Van Zandt", "Wood",
        ],
    },
    "gulf-coast": {
        "label": "Gulf Coast",
        "counties": [
            "Aransas", "Austin", "Brazoria", "Brooks", "Calhoun",
            "Cameron", "Chambers", "Colorado", "Duval", "Fort Bend",
            "Galveston", "Harris", "Hidalgo", "Jackson", "Jefferson",
            "Jim Hogg", "Jim Wells", "Kenedy", "Kleberg", "Liberty",
            "Matagorda", "Nueces", "Orange", "Refugio", "San Patricio",
            "Starr", "Victoria", "Waller", "Wharton", "Willacy",
        ],
    },
    "north-texas": {
        "label": "North Texas / Barnett",
        "counties": [
            "Clay", "Cooke", "Denton", "Eastland", "Erath",
            "Hood", "Jack", "Johnson", "Montague", "Palo Pinto",
            "Parker", "Shackelford", "Somervell", "Stephens",
            "Tarrant", "Throckmorton", "Wichita", "Wise", "Young",
        ],
    },
    "panhandle": {
        "label": "Texas Panhandle",
        "counties": [
            "Carson", "Collingsworth", "Dallam", "Gray", "Hansford",
            "Hartley", "Hemphill", "Hutchinson", "Lipscomb", "Moore",
            "Ochiltree", "Oldham", "Potter", "Roberts", "Sherman",
            "Wheeler",
        ],
    },
    "south-texas": {
        "label": "South Texas",
        "counties": [
            "Caldwell", "Guadalupe", "Hays", "Kinney", "Uvalde",
            "Bexar", "Comal", "Fayette", "Goliad",
            "Lee", "Milam", "Robertson", "Washington",
        ],
    },
    "central-texas": {
        "label": "Central Texas",
        "counties": [
            "Bell", "Bosque", "Brown", "Burnet", "Coleman",
            "Comanche", "Concho", "Coryell", "Erath", "Falls",
            "Fisher", "Hamilton", "Haskell", "Hill", "Jones",
            "Lampasas", "McCulloch", "McLennan", "Mason", "Menard",
            "Mills", "Runnels", "San Saba", "Stonewall", "Taylor",
            "Tom Green",
        ],
    },
}


def list_regions():
    print("\nTexas Petroleum Regions:")
    print(f"  {'Region':25s} {'Counties':>8s}  Label")
    print(f"  {'-'*25} {'-'*8}  {'-'*30}")
    total = 0
    for key, info in sorted(REGIONS.items()):
        n = len(info["counties"])
        total += n
        print(f"  {key:25s} {n:>8d}  {info['label']}")
    print(f"\n  Total counties: {total}")
    print(f"\nUsage:")
    print(f"  python build_county_geojson.py --region permian")
    print(f"  python build_county_geojson.py --region all-regions")
    print(f"  python build_county_geojson.py --list-regions")
    print(f"  python build_county_geojson.py Andrews Ector Midland")


def main():
    if "--list-regions" in sys.argv or "--help" in sys.argv or len(sys.argv) == 1:
        list_regions()
        return

    if "--region" in sys.argv:
        idx = sys.argv.index("--region")
        region_key = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""

        if region_key == "all-regions":
            e = create_engine(DEFAULT_CONN)
            print("Querying all wells (this may take a minute)...")
            gj = build_geojson(e)
            all_features = gj.get("features", [])
            print(f"  Total features: {len(all_features):,}\n")

            for key, info in sorted(REGIONS.items()):
                county_set = {c.upper() for c in info["counties"]}
                filtered = [
                    f for f in all_features
                    if (f["properties"].get("county") or "").upper() in county_set
                ]
                if not filtered:
                    print(f"  {info['label']:30s} — no wells")
                    continue

                out = f"wells_{key.replace('-','_')}.geojson"
                out_gj = {
                    "type": "FeatureCollection",
                    "metadata": {
                        "region": info["label"],
                        "total_wells": len(filtered),
                        "counties": len(info["counties"]),
                    },
                    "features": filtered,
                }
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(out_gj, f)
                size_mb = len(json.dumps(out_gj)) / (1024 * 1024)
                print(f"  {info['label']:30s} {len(filtered):>8,} wells  {out} ({size_mb:.1f} MB)")

            print("\nDone!")
            return

        if region_key not in REGIONS:
            print(f"Unknown region: {region_key}")
            list_regions()
            return

        info = REGIONS[region_key]
        counties = [c.upper() for c in info["counties"]]
        label = info["label"]
        out_name = f"wells_{region_key.replace('-','_')}.geojson"
    else:
        counties = [c.upper() for c in sys.argv[1:] if not c.startswith("-")]
        label = counties[0] if len(counties) == 1 else "Custom"
        out_name = "wells.geojson"

    print(f"Building GeoJSON for {label} ({len(counties)} counties)...")
    e = create_engine(DEFAULT_CONN)
    gj = build_geojson(e)

    filtered = [
        f for f in gj["features"]
        if (f["properties"].get("county") or "").upper() in counties
    ]

    gj["features"] = filtered
    gj["metadata"]["total_wells"] = len(filtered)
    gj["metadata"]["filter"] = label

    with open(out_name, "w", encoding="utf-8") as f:
        json.dump(gj, f)

    size_mb = len(json.dumps(gj)) / (1024 * 1024)
    print(f"Wrote {len(filtered):,} wells → {out_name} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
