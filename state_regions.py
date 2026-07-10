"""
state_regions.py
=================
State-region definitions, originally built via Region
Builder, then retrofitted by migrate_state_regions.py
to use updated zoom thresholds.

Each entry is a 3-tuple:
    (state_code, [county_names], (lat, lon, zoom))

Same shape as petroleum_regions.py so well_map can read
either interchangeably.
"""

STATE_REGIONS = {
    "— none —": (None, [], None),

    "East Texas": ("TX", [
        "Anderson", "Angelina", "Austin", "Bowie", "Brazoria",
        "Brazos", "Burleson", "Calhoun", "Camp", "Cass",
        "Chambers", "Cherokee", "Collin", "Colorado", "Dallas",
        "Delta", "Denton", "Ellis", "Falls", "Fannin",
        "Fayette", "Fort Bend", "Franklin", "Freestone", "Galveston",
        "Grayson", "Gregg", "Grimes", "Hardin", "Harris",
        "Harrison", "Henderson", "Hill", "Hopkins", "Houston",
        "Hunt", "Jackson", "Jasper", "Jefferson", "Kaufman",
        "Lamar", "Lavaca", "Lee", "Leon", "Liberty",
        "Limestone", "Madison", "Marion", "Matagorda", "Milam",
        "Montgomery", "Morris", "Nacogdoches", "Navarro", "Newton",
        "Orange", "Panola", "Polk", "Rains", "Red River",
        "Robertson", "Rockwall", "Rusk", "Sabine", "San Augustine",
        "San Jacinto", "Shelby", "Smith", "Titus", "Trinity",
        "Tyler", "Upshur", "Van Zandt", "Victoria", "Walker",
        "Waller", "Washington", "Wharton", "Wood",
    ], (31.4172, -95.5747, 6)),

    "South Texas": ("TX", [
        "Aransas", "Atascosa", "Bee", "Brooks", "Cameron",
        "DeWitt", "Dimmit", "Duval", "Frio", "Goliad",
        "Hidalgo", "Jim Hogg", "Jim Wells", "Karnes", "Kenedy",
        "Kleberg", "La Salle", "Live Oak", "Maverick", "McMullen",
        "Nueces", "Refugio", "San Patricio", "Starr", "Victoria",
        "Webb", "Willacy", "Zapata", "Zavala",
    ], (27.8980, -98.2443, 7)),

    "Central Texas": ("TX", [
        "Atascosa", "Bandera", "Bastrop", "Bell", "Bexar",
        "Blanco", "Bosque", "Brown", "Burnet", "Caldwell",
        "Callahan", "Coke", "Coleman", "Comal", "Comanche",
        "Concho", "Coryell", "Crockett", "DeWitt", "Eastland",
        "Edwards", "Erath", "Falls", "Fayette", "Frio",
        "Gillespie", "Glasscock", "Gonzales", "Guadalupe", "Hamilton",
        "Hays", "Hill", "Hood", "Howard", "Irion",
        "Johnson", "Karnes", "Kendall", "Kerr", "Kimble",
        "Kinney", "Lampasas", "Lavaca", "Lee", "Llano",
        "Martin", "Mason", "McCulloch", "McLennan", "Medina",
        "Menard", "Midland", "Milam", "Mills", "Mitchell",
        "Nolan", "Reagan", "Real", "Runnels", "San Saba",
        "Schleicher", "Somervell", "Sterling", "Sutton", "Taylor",
        "Tom Green", "Travis", "Uvalde", "Val Verde", "Williamson",
        "Wilson", "Zavala",
    ], (30.8155, -99.0097, 6)),

    "North Texas": ("TX", [
        "Archer", "Armstrong", "Bailey", "Baylor", "Borden",
        "Briscoe", "Carson", "Castro", "Childress", "Clay",
        "Cochran", "Collingsworth", "Cooke", "Cottle", "Crosby",
        "Dallam", "Dawson", "Deaf Smith", "Dickens", "Donley",
        "Fisher", "Floyd", "Foard", "Gaines", "Garza",
        "Gray", "Hale", "Hall", "Hansford", "Hardeman",
        "Hartley", "Haskell", "Hemphill", "Hockley", "Hutchinson",
        "Jack", "Jones", "Kent", "King", "Knox",
        "Lamb", "Lipscomb", "Lubbock", "Lynn", "Montague",
        "Moore", "Motley", "Ochiltree", "Oldham", "Palo Pinto",
        "Parker", "Parmer", "Potter", "Randall", "Roberts",
        "Scurry", "Shackelford", "Sherman", "Stephens", "Stonewall",
        "Swisher", "Tarrant", "Terry", "Throckmorton", "Wheeler",
        "Wichita", "Wilbarger", "Wise", "Yoakum", "Young",
    ], (34.1322, -100.6451, 6)),

    "West Texas": ("TX", [
        "Andrews", "Brewster", "Crane", "Culberson", "Ector",
        "El Paso", "Glasscock", "Hudspeth", "Jeff Davis", "Loving",
        "Martin", "Midland", "Pecos", "Presidio", "Reagan",
        "Reeves", "Terrell", "Upton", "Ward", "Winkler",
    ], (31.3560, -103.1380, 6)),
}
