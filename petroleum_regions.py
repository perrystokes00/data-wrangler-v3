"""
petroleum_regions.py
=====================
PETROLEUM_REGIONS — well-known producing-area definitions,
mapped to their constituent counties per state.

Each entry is a 3-tuple:
    (state_code, [county_names], (center_lat, center_lon, zoom))

The center tuple powers auto-zoom in well_map. Centers were
computed once via migrate_petroleum_regions.py from TIGER
county centroids. Re-run that script if counties change.

Source of truth: WranglerView prototype_filter.py
Last sync:        May 26, 2026
Centers migrated: migrate_petroleum_regions.py
"""

PETROLEUM_REGIONS = {
    "— none —": (None, [], None),

    "Permian Basin (TX)": ("TX", [
        "Andrews", "Borden", "Crane", "Crockett", "Culberson",
        "Dawson", "Ector", "Gaines", "Glasscock", "Howard",
        "Irion", "Jeff Davis", "Loving", "Martin", "Midland",
        "Mitchell", "Nolan", "Pecos", "Reagan", "Reeves",
        "Schleicher", "Scurry", "Sterling", "Sutton", "Terrell",
        "Terry", "Upton", "Val Verde", "Ward", "Winkler",
        "Yoakum",
    ], (31.7246, -102.0702, 6)),

    "Eagle Ford (TX)": ("TX", [
        "Atascosa", "Bee", "DeWitt", "Dimmit", "Frio",
        "Gonzales", "Karnes", "La Salle", "Lavaca", "Live Oak",
        "Maverick", "McMullen", "Medina", "Webb", "Wilson",
        "Zapata", "Zavala",
    ], (28.6694, -98.6080, 7)),

    "East Texas": ("TX", [
        "Anderson", "Camp", "Cass", "Cherokee", "Franklin",
        "Freestone", "Gregg", "Harrison", "Henderson", "Houston",
        "Leon", "Limestone", "Marion", "Morris", "Nacogdoches",
        "Navarro", "Panola", "Rusk", "Shelby", "Smith",
        "Titus", "Upshur", "Van Zandt", "Wood",
    ], (32.3040, -95.1806, 7)),

    "Gulf Coast (TX)": ("TX", [
        "Aransas", "Austin", "Brazoria", "Brooks", "Calhoun",
        "Cameron", "Chambers", "Colorado", "Duval", "Fort Bend",
        "Galveston", "Harris", "Hidalgo", "Jackson", "Jefferson",
        "Jim Hogg", "Jim Wells", "Kenedy", "Kleberg", "Liberty",
        "Matagorda", "Nueces", "Orange", "Refugio", "San Patricio",
        "Starr", "Victoria", "Waller", "Wharton", "Willacy",
    ], (28.4373, -96.6714, 6)),

    "Barnett / North Texas": ("TX", [
        "Clay", "Cooke", "Denton", "Eastland", "Erath",
        "Hood", "Jack", "Johnson", "Montague", "Palo Pinto",
        "Parker", "Shackelford", "Somervell", "Stephens", "Tarrant",
        "Throckmorton", "Wichita", "Wise", "Young",
    ], (32.9719, -98.1219, 7)),

    "Texas Panhandle": ("TX", [
        "Carson", "Collingsworth", "Dallam", "Gray", "Hansford",
        "Hartley", "Hemphill", "Hutchinson", "Lipscomb", "Moore",
        "Ochiltree", "Oldham", "Potter", "Roberts", "Sherman",
        "Wheeler",
    ], (35.7850, -101.3173, 7)),

    "Hugoton Embayment (KS)": ("KS", [
        "Finney", "Grant", "Gray", "Hamilton", "Haskell",
        "Hodgeman", "Kearny", "Meade", "Morton", "Seward",
        "Stanton", "Stevens", "Ford", "Clark", "Comanche",
        "Kiowa", "Edwards", "Pawnee", "Ness", "Lane",
        "Scott", "Wichita",
    ], (37.7747, -100.5422, 7)),

    "Central Kansas Uplift": ("KS", [
        "Barton", "Ellsworth", "Lincoln", "McPherson", "Marion",
        "Rice", "Rush", "Russell", "Saline", "Stafford",
        "Ellis", "Osborne", "Rooks", "Smith", "Phillips",
        "Norton", "Graham", "Trego",
    ], (38.9336, -98.7642, 7)),

    "Sedgwick Basin (KS)": ("KS", [
        "Butler", "Cowley", "Harvey", "Kingman", "Pratt",
        "Reno", "Sedgwick", "Sumner", "Harper", "Barber",
        "Greenwood", "Elk",
    ], (37.5746, -97.5200, 7)),

    "Anadarko Basin (OK)": ("OK", [
        "Beckham", "Custer", "Washita", "Caddo", "Blaine",
        "Canadian", "Grady", "Roger Mills", "Dewey",
    ], (35.4981, -98.7838, 8)),

    "SCOOP (OK)": ("OK", [
        "Garvin", "Grady", "McClain", "Stephens", "Carter",
    ], (34.6935, -97.5550, 9)),

    "STACK (OK)": ("OK", [
        "Kingfisher", "Canadian", "Blaine", "Caddo",
    ], (35.6344, -98.1833, 9)),

    "Arkoma Basin (OK)": ("OK", [
        "Pittsburg", "Latimer", "Haskell", "Le Flore", "McIntosh",
        "Sequoyah",
    ], (35.1323, -95.2068, 8)),
}
