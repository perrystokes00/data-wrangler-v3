import sys, importlib.util, pathlib

mod_path = pathlib.Path.home() / "Downloads" / "pdf_survey_catalog.py"
print(f"Loading: {mod_path} (exists={mod_path.exists()})")

spec = importlib.util.spec_from_file_location("pdf_sc_new", str(mod_path))
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

import inspect
src = inspect.getsource(mod.extract_stations)
print(f"New version: {'_TEXT_COL_PATTERNS' in src}")

path = sys.argv[1]
r = mod.extract_stations(path)
print(f"Columns: {r['columns_found']}")
print(f"Stations: {len(r['stations'])}")
print(f"Error: {r['error']}")
if r['stations']:
    print(f"First: {r['stations'][0]}")
    print(f"Last:  {r['stations'][-1]}")
