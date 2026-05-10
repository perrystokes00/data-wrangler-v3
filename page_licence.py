"""
page_licence.py  —  Data Wrangler Licence Screen
=================================================
Shown when:
  - No licence key saved (first launch)
  - Licence expired
  - Key revoked

Call render() from app.py before showing the splash/pipeline.
Returns True if licence is valid and app should proceed.
"""

import streamlit as st
from modules.licence import activate_licence, get_licence_status


def render() -> bool:
    """
    Returns True if licence is valid and app should proceed.
    Returns False if app should be blocked (shows UI and stops).
    """
    status = get_licence_status()

    # ── Valid licence ─────────────────────────────────────────────────────────
    if status.valid:
        # Show a subtle warning banner in the last 5 days
        if 0 < status.days_remaining <= 5:
            st.warning(
                f"⚠️ Your trial expires in **{status.days_remaining} day(s)**. "
                f"Contact the Data Wrangler team to purchase a licence."
            )
        return True

    # ── No key yet → activation screen ───────────────────────────────────────
    if status.message == "NO_KEY":
        _render_activation_screen()
        return False

    # ── Expired or revoked → block screen ────────────────────────────────────
    _render_blocked_screen(status.message)
    return False


# ── Activation screen ─────────────────────────────────────────────────────────

def _render_activation_screen():
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] { display: none !important; }
    </style>
    """, unsafe_allow_html=True)

    col = st.columns([1, 2, 1])[1]
    with col:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown(
            """
            <div style='text-align:center;margin-bottom:1.5rem'>
              <div style='font-size:2.8rem;font-weight:900;color:#C8922A;
                          letter-spacing:-1px;line-height:1'>DATA WRANGLER</div>
              <div style='font-size:.85rem;color:#7aaac8;margin-top:.3rem;
                          letter-spacing:2px;text-transform:uppercase'>
                Licence Activation
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.info(
            "Enter your licence key to activate Data Wrangler. "
            "Keys are in the format **DW-XXXX-XXXX-XXXX-XXXX**. "
            "Contact the Data Wrangler team if you need a trial key."
        )

        key = st.text_input(
            "Licence Key",
            placeholder="DW-XXXX-XXXX-XXXX-XXXX",
            max_chars=22,
        ).strip().upper()

        if st.button("Activate", type="primary", use_container_width=True):
            if not key:
                st.error("Please enter a licence key.")
            else:
                with st.spinner("Validating licence..."):
                    result = activate_licence(key)
                if result.valid:
                    st.success(
                        f"✅ Activated! Welcome, **{result.customer}**. "
                        f"Your {result.days_remaining}-day trial starts today."
                    )
                    st.rerun()
                else:
                    st.error(f"❌ {result.message}")

        st.markdown("<br>", unsafe_allow_html=True)
        st.caption(
            "Need a licence key? Contact the Data Wrangler team. "
            "An internet connection is required for activation."
        )


# ── Blocked screen ────────────────────────────────────────────────────────────

def _render_blocked_screen(message: str):
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] { display: none !important; }
    </style>
    """, unsafe_allow_html=True)

    col = st.columns([1, 2, 1])[1]
    with col:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown(
            """
            <div style='text-align:center;margin-bottom:1.5rem'>
              <div style='font-size:2.8rem;font-weight:900;color:#C8922A;
                          letter-spacing:-1px;line-height:1'>DATA WRANGLER</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.error(f"🔒 {message}")

        st.markdown(
            """
            <div style='background:#1a2a3a;border:1px solid #2e5a7a;border-radius:8px;
                        padding:1.2rem 1.5rem;margin-top:1rem;text-align:center'>
              <div style='font-size:.85rem;color:#a0c8e8;margin-bottom:.5rem'>
                To purchase a full licence or extend your trial:
              </div>
              <div style='font-size:1.1rem;font-weight:700;color:#C8922A'>
                support@datawranglersolutions.com
              </div>
              <div style='font-size:.75rem;color:#5a8aaa;margin-top:.5rem'>
                Annual licence $25,000 · Enterprise pricing available
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<br>", unsafe_allow_html=True)

        # Allow re-entry of a new key (e.g. after purchasing full licence)
        with st.expander("Already have a new licence key? Enter it here"):
            new_key = st.text_input(
                "New Licence Key",
                placeholder="DW-XXXX-XXXX-XXXX-XXXX",
                max_chars=22,
                key="blocked_new_key",
            ).strip().upper()
            if st.button("Activate New Key", type="primary", use_container_width=True):
                if not new_key:
                    st.error("Please enter a licence key.")
                else:
                    with st.spinner("Validating licence..."):
                        from modules.licence import activate_licence
                        # Delete old licence.json so fresh activation works
                        from pathlib import Path
                        lf = Path("licence.json")
                        if lf.exists():
                            lf.unlink()
                        result = activate_licence(new_key)
                    if result.valid:
                        st.success(
                            f"✅ Activated! Welcome back, **{result.customer}**. "
                            f"Your licence is valid for {result.days_remaining} days."
                        )
                        st.rerun()
                    else:
                        st.error(f"❌ {result.message}")
