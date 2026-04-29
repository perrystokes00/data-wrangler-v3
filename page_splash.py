"""
page_splash.py  —  Data Wrangler · Splash Screen
"""

import base64
import pathlib
import streamlit as st
import streamlit.components.v1 as components


def _img_b64(path: str) -> str | None:
    p = pathlib.Path(path)
    if p.exists():
        return base64.b64encode(p.read_bytes()).decode()
    return None


def render(S):
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] { display: none !important; }
    header { display: none !important; }
    footer { display: none !important; }
    .block-container { padding: 0 !important; margin: 0 !important; max-width: 100% !important; }
    iframe { display: block !important; border: none !important; }
    div[data-testid="stButton"] > button {
        background: #C8922A !important; color: white !important;
        border: none !important; border-radius: 8px !important;
        font-size: 15px !important; font-weight: 700 !important;
        padding: 11px 52px !important; letter-spacing: 0.5px !important;
        cursor: pointer !important;
        box-shadow: 0 4px 18px rgba(200,146,42,0.4) !important;
                margin-top: 4px !important;
    }
    div[data-testid="stButton"] > button:hover {
        background: #B07820 !important; transform: translateY(-1px) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    img_b64 = _img_b64("assets/data_wrangler.png") or _img_b64("data_wrangler.png") or _img_b64("assets/cowboy.png") or _img_b64("cowboy.png")
    img_tag = (
        f'<img src="data:image/png;base64,{img_b64}" class="cowboy-img" alt="data wrangler"/>'
        if img_b64 else '<div style="font-size:160px;line-height:1;">🤠</div>'
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ height: 100%; width: 100%; overflow: hidden; background: #0D1B2A; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; }}
.wrap {{ height: 100%; display: flex; flex-direction: column; }}
.topbar {{ height: 5px; background: #C8922A; flex-shrink: 0; }}
.main {{
    flex: 1; display: flex; min-height: 0;
    padding: 0 clamp(24px, 4vw, 64px);
    gap: clamp(16px, 2.5vw, 48px);
    width: 100%; overflow: hidden;
}}
.left {{
    flex: 1; display: flex; flex-direction: column;
    justify-content: center; min-width: 0; overflow: hidden; padding: 8px 0;
}}
.eyebrow {{
    font-size: clamp(9px, 0.85vw, 13px); font-weight: 700; letter-spacing: 3px;
    color: #7AABCB; text-transform: uppercase; margin-bottom: clamp(6px, 1vh, 12px);
}}
.title-data {{
    font-size: clamp(40px, 5.5vw, 80px);
    font-weight: 900; line-height: 1; color: #FFFFFF; letter-spacing: -2px;
}}
.title-wrangler {{
    font-size: clamp(40px, 5.5vw, 80px);
    font-weight: 900; line-height: 1; color: #C8922A; letter-spacing: -2px;
}}
.gold-rule {{
    width: clamp(40px, 4vw, 72px); height: 4px;
    background: #C8922A; border-radius: 2px; margin: clamp(8px, 1.2vh, 18px) 0;
}}
.subtitle {{
    font-size: clamp(11px, 1.3vw, 18px); color: #A8CFEA;
    font-style: italic; margin-bottom: clamp(2px, 0.4vh, 6px);
}}
.tagline {{
    font-size: clamp(10px, 1.0vw, 14px); color: #4A7A9A;
    font-weight: 500; margin-bottom: clamp(10px, 1.8vh, 24px);
}}
.grid {{
    display: grid; grid-template-columns: 1fr 1fr;
    gap: clamp(4px, 0.6vh, 8px); margin-bottom: clamp(10px, 1.8vh, 24px);
}}
.pill {{
    background: #152536; border: 1px solid #1E3A5A; border-radius: 7px;
    padding: clamp(5px, 0.8vh, 10px) clamp(8px, 0.9vw, 14px);
    display: flex; align-items: center; gap: 6px;
    font-size: clamp(10px, 1.0vw, 14px); font-weight: 600; color: #C8E4F8;
}}
.tech {{
    font-size: clamp(9px, 0.85vw, 13px); color: #9BBFD8; font-weight: 500;
    letter-spacing: 1px; border-top: 1px solid #1E3A5A;
    padding-top: clamp(8px, 1vh, 14px);
}}
.right {{
    width: clamp(240px, 34vw, 500px); flex-shrink: 0;
    display: flex; align-items: flex-end; justify-content: center;
    overflow: hidden; position: relative; padding-bottom: 5px;
}}
.cowboy-img {{
    width: 100%; height: 100%;
    object-fit: contain; object-position: bottom center;
    display: block; position: relative; z-index: 0;
}}
.bottombar {{
    flex-shrink: 0; background: #091420; padding: 5px clamp(24px, 4vw, 64px);
    display: flex; justify-content: space-between; align-items: center;
    border-top: 1px solid #1A2E40;
}}
.bl {{ font-size: clamp(9px, 0.85vw, 13px); color: #FFFFFF; font-weight: 500; }}
.br {{ font-size: clamp(9px, 0.85vw, 13px); color: #C8922A; font-weight: 600; letter-spacing: 1px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar"></div>
  <div class="main">
    <div class="left">
      <div class="eyebrow">PPDM 3.9 &nbsp;·&nbsp; SQL Server &nbsp;·&nbsp; Oracle &nbsp;·&nbsp; Snowflake</div>
      <div class="title-data">Data</div>
      <div class="title-wrangler">Wrangler</div>
      <div class="gold-rule"></div>
      <div class="subtitle">AI-Assisted Petroleum Data Management</div>
      <div class="tagline">Round up your data. Drive it into PPDM.</div>
      <div style="display:flex;gap:clamp(6px,0.8vw,12px);margin-bottom:clamp(8px,1.2vh,16px);">
        <div style="border-radius:20px;padding:clamp(3px,0.5vh,6px) clamp(10px,1vw,16px);font-size:clamp(9px,0.9vw,13px);font-weight:700;letter-spacing:0.5px;border:1px solid;display:flex;align-items:center;gap:5px;background:#1A2E4A;border-color:#5A9ABB;color:#AAD4EE;">⬛ SQL Server</div>
        <div style="border-radius:20px;padding:clamp(3px,0.5vh,6px) clamp(10px,1vw,16px);font-size:clamp(9px,0.9vw,13px);font-weight:700;letter-spacing:0.5px;border:1px solid;display:flex;align-items:center;gap:5px;background:#2A1A0A;border-color:#BB6A30;color:#EEA060;">🔶 Oracle</div>
        <div style="border-radius:20px;padding:clamp(3px,0.5vh,6px) clamp(10px,1vw,16px);font-size:clamp(9px,0.9vw,13px);font-weight:700;letter-spacing:0.5px;border:1px solid;display:flex;align-items:center;gap:5px;background:#0A1A2A;border-color:#4A9ACC;color:#88CCEE;">❄️ Snowflake</div>
      </div>
      <div class="grid">
        <div class="pill">📋 Schema Agnostic</div>
        <div class="pill">🗄️ Database Agnostic</div>
        <div class="pill">⚡ Interactive Processing</div>
        <div class="pill">📦 Batch Processing</div>
        <div class="pill">🔗 Auto FK Detection &amp; Seeding</div>
        <div class="pill" style="flex-direction:column;align-items:flex-start;gap:2px;"><span>📏 BUILT-IN Data Governance</span><span style="font-size:clamp(8px,0.8vw,11px);font-weight:400;color:#A8CFEA;">Normalization &amp; Validation</span></div>
        <div style="grid-column:span 2;background:linear-gradient(135deg,#1A1A3A 0%,#0D2A3A 100%);border:2px solid #C8922A;border-radius:10px;padding:clamp(8px,1.2vh,14px) 20px;display:flex;align-items:center;justify-content:center;gap:10px;font-size:clamp(12px,1.4vw,18px);font-weight:900;color:#C8922A;letter-spacing:1px;box-shadow:0 0 20px rgba(200,146,42,0.3);">🧠 &nbsp; AI HELP ASSISTANT</div>
      </div>
      <div class="tech">Python &nbsp;·&nbsp; Streamlit &nbsp;·&nbsp; SQL Server &nbsp;·&nbsp; Oracle &nbsp;·&nbsp; Snowflake &nbsp;·&nbsp; PPDM 3.9</div>
    </div>
    <div class="right">{img_tag}</div>
  </div>
  <div class="bottombar">
    <span class="bl"></span>
    <span class="br">Wrangling data since forever</span>
  </div>
</div>
</body>
</html>"""

    components.html(html, height=640, scrolling=False)

    # Native Streamlit button below the iframe — reliably works
    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        if st.button("Get Started →", use_container_width=True):
            S.show_splash = False
            st.rerun()
