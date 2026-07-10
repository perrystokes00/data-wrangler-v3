"""Find Oil_Fields_USA.shp wherever it is, show its DBF columns + field names,
so the per-feature loader maps the right name column."""
import os, glob
import geopandas as gpd

# search the training tree
roots = [
    r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training",
]
found = None
for r in roots:
    for p in glob.glob(os.path.join(r, "**", "Oil_Fields_USA.shp"), recursive=True):
        found = p; break
if not found:
    # fall back: any field-ish shapefile
    for r in roots:
        for p in glob.glob(os.path.join(r, "**", "*ield*.shp"), recursive=True):
            found = p; break

if not found:
    print("no field shapefile found under training/")
else:
    print(f"found: {found}\n")
    gdf = gpd.read_file(found)
    print(f"features: {len(gdf)}")
    print(f"geometry types: {sorted(gdf.geom_type.unique())}")
    print(f"columns: {[c for c in gdf.columns if c!='geometry']}\n")
    # print first 8 rows of the attribute table (no geometry)
    import pandas as pd
    pd.set_option('display.max_columns', None); pd.set_option('display.width', 200)
    print(gdf.drop(columns='geometry').head(8).to_string())
