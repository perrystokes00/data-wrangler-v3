"""file_viewer.py (modules) — shim; canonical implementation lives in the repo-root
file_viewer.py, which has the nest-safe _vsection sections and PyMuPDF PDF render
(the base64-iframe approach crashed the browser; bare st.expander cannot nest in the
Documents page). Kept so `from modules.file_viewer import ...` keeps working.
"""
from file_viewer import *  # noqa: F401,F403
