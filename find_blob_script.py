"""find_blob_script.py — locate the survey-blob/outline script by scanning all .py
files for geometry-aggregation signatures. py find_blob_script.py"""
import glob, os
# signatures a "blob around all lines in a survey" script would have
sigs = ["unary_union", "buffer(", "convex_hull", "concave", "alphashape",
        "alpha_shape", "dissolve", "MultiLineString", "SURVEY_NAME",
        "seis_set", "survey_outline", "geog", "MultiPoint"]
hits = {}
for f in glob.glob("**/*.py", recursive=True):
    try:
        t = open(f, encoding="utf-8", errors="ignore").read()
    except Exception:
        continue
    found = [s for s in sigs if s in t]
    # a blob script would combine buffer/union/hull WITH survey/seis terms
    geo = any(s in found for s in ("unary_union","buffer(","convex_hull","concave","alphashape","alpha_shape","dissolve","MultiLineString"))
    survey = any(s in found for s in ("SURVEY_NAME","seis_set","survey_outline"))
    if geo and survey:
        hits[f] = found
for f, found in sorted(hits.items(), key=lambda kv: -len(kv[1])):
    print(f"{f}")
    print(f"    matches: {', '.join(found)}")
if not hits:
    print("No file combines geometry-aggregation with survey terms.")
    print("The blob script may have a different name — list your .py files:")
    for f in sorted(glob.glob("*.py")):
        print("   ", f)
