"""page_data_model.py — PPDM Data Model PDF Viewer."""
import streamlit as st
from dataview.core.ui_helpers import shdr, pill, mrow

def render(S):

    # ── PPDM Data Model Viewer ────────────────────────────────────────────
    import streamlit.components.v1 as _components
    import os as _os

    # Locate viewer HTML — same directory as app.py
    _viewer_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                 "ppdm_viewer.html")
    if not _os.path.exists(_viewer_path):
        st.error(
            f"Viewer file not found: `{_viewer_path}`\n\n"
            "Copy `ppdm_viewer.html` to the same folder as `app.py`."
        )
    else:
        with open(_viewer_path, "r", encoding="utf-8") as _vf:
            _viewer_html = _vf.read()
        # Render full-height — subtract topbar height
        _components.html(_viewer_html, height=820, scrolling=False)
