"""
page_vault.py — dedicated Vault page.

Runs the vault stage on its own against the catalog that's already in the DB
(no scan/extract/capture), using the SAME pipeline_run._stage_vault the full run
uses, so routing/placement can't drift. Dry-run by default; Apply places files
and stamps. The [vault-fetch] / [vault-phase] timing shows inline.

Wire into the app router with:  page_vault.render()
(aliases main/show/app point at render() for whatever convention your router uses).
"""
import os
import time
import streamlit as st
from dataview.import_data import pipeline_run as pr

SCHEMA = "file_catalog"


def _get_engine():
    """Reuse the app's live connection from session_state if present, else build
    one with pipeline_run._engine (same builder the pipeline uses)."""
    for k in ("engine", "eng", "sql_engine", "conn_engine", "db_engine"):
        e = st.session_state.get(k)
        if e is not None and hasattr(e, "connect"):
            return e, f"session_state[{k!r}]"
    server = st.session_state.get("server") or r"localhost\SQLEXPRESS"
    database = st.session_state.get("database") or "DataView_Demo"
    return pr._engine(server, database), f"{server} / {database}"


def render(engine=None):
    st.title("📦 Vault")
    st.caption("Place catalogued files into the governed vault — standalone, "
               "against the current catalog. No scan / extract / capture.")

    if engine is not None:
        eng, src = engine, "workbench engine"
    else:
        try:
            eng, src = _get_engine()
        except Exception as e:
            st.error(f"Could not get a DB connection: {e}")
            return

    c1, c2, c3 = st.columns(3)
    vault_root = c1.text_input("Vault root", r"C:\Bulk\Vault")
    mode = c2.selectbox("Mode", ["copy", "hardlink"], index=0)
    workers = c3.number_input("Copy workers", min_value=1, max_value=32, value=8, step=1)
    apply = st.checkbox(
        "Apply — place files + stamp VAULTED_AT / VAULT_PATH "
        "(off = dry-run: plan + fetch timing only, no files touched)",
        value=False)

    st.caption(f"Connection: {src}  ·  schema: {SCHEMA}")

    if not st.button("▶ Run vault", type="primary", use_container_width=True):
        return

    os.environ["VAULT_COPY_WORKERS"] = str(int(workers))
    logs = []
    with st.spinner("Running vault…"):
        t0 = time.monotonic()
        try:
            stats = pr._stage_vault(eng, SCHEMA, vault_root, mode, apply, logs.append)
        except Exception as e:
            st.error(f"Vault failed: {e}")
            st.code("\n".join(map(str, logs)) or "(no output)")
            return
        dt = time.monotonic() - t0

    if isinstance(stats, dict):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Planned", f"{stats.get('vault_total', 0):,}")
        m2.metric("Placed", f"{stats.get('vault_placed', 0):,}")
        m3.metric("Already vaulted", f"{stats.get('vault_exists', 0):,}")
        m4.metric("Failed", f"{stats.get('vault_failed', 0):,}")

    (st.success if not stats.get("vault_failed") else st.warning)(
        f"{'APPLY' if apply else 'DRY-RUN'} done in {dt:.1f}s")

    phase = [str(l) for l in logs
             if any(tag in str(l) for tag in ("[vault-fetch]", "[vault-phase]", "[vault-wait]"))]
    if phase:
        st.subheader("Timing")
        st.code("\n".join(phase))

    with st.expander("Full vault log", expanded=False):
        st.code("\n".join(map(str, logs)) or "(no output)")


# convenience aliases so the page works with whatever the router calls
main = show = app = render

if __name__ == "__main__":     # allows: streamlit run page_vault.py
    render()
