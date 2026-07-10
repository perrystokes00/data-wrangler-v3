"""Is geography's 24,748 km2 correct, or is the shapefile's AREA_SQKM (8037)?
Compute the polygon's lat/lon span and rough expected area independently, so we
know which number to trust before building the loader."""
import os
import geopandas as gpd

SHP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_shapefiles\Seismic_3D_Surveys.shp"
gdf = gpd.read_file(SHP)
if gdf.crs and gdf.crs.to_epsg() != 4326:
    gdf = gdf.to_crs(4326)

import math
print("=== independent area sanity check (from raw coordinates) ===\n")
name_col = next((c for c in gdf.columns if c.lower() in ("survey_nam","survey_name","name")), None)
area_col = next((c for c in gdf.columns if "area" in c.lower()), None)

for _, row in gdf.iterrows():
    g = row.geometry
    minx, miny, maxx, maxy = g.bounds
    dlon = maxx - minx
    dlat = maxy - miny
    # rough area: at mid-latitude, 1 deg lat ~111km, 1 deg lon ~111km*cos(lat)
    midlat = (miny + maxy) / 2
    km_lat = dlat * 111.0
    km_lon = dlon * 111.0 * math.cos(math.radians(midlat))
    approx_km2 = abs(km_lat * km_lon)   # bbox rectangle approx
    nm = row[name_col] if name_col else "?"
    label = row[area_col] if area_col else None
    # also get shapely's planar-degrees area converted crudely
    print(f"   {str(nm):22}")
    print(f"      bbox span: {dlon:.3f}deg lon x {dlat:.3f}deg lat  (~{km_lon:.0f}km x {km_lat:.0f}km)")
    print(f"      bbox-rect area  ~ {approx_km2:,.0f} km2")
    print(f"      shapefile label = {label} km2")
    print()
print("If bbox-rect area matches the geography STArea (~thousands), the shapefile")
print("AREA_SQKM label is just wrong/synthetic and geography is correct.")
