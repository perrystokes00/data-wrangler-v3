"""
modules/inv_auth.py
Inventory authentication helpers for Streamlit session state.
"""
import streamlit as st
from sqlalchemy.engine import Engine


def is_logged_in() -> bool:
    return st.session_state.get("inv_logged_in", False)


def current_user() -> dict:
    return {
        "user_id":   st.session_state.get("inv_user_id", ""),
        "full_name": st.session_state.get("inv_user_name", ""),
        "email":     st.session_state.get("inv_user_email", ""),
        "role":      st.session_state.get("inv_user_role", ""),
    }


def login(user: dict, engine=None):
    st.session_state["inv_logged_in"]  = True
    st.session_state["inv_user_id"]    = user["user_id"]
    st.session_state["inv_user_name"]  = user["full_name"]
    st.session_state["inv_user_email"] = user["email"]
    st.session_state["inv_user_role"]  = user["role"]
    try:
        from modules.audit_log import audit_login
        audit_login(engine, user)
    except Exception:
        pass


def logout(engine=None):
    try:
        if engine:
            from modules.audit_log import audit_logout
            audit_logout(engine, current_user())
    except Exception:
        pass
    for key in ["inv_logged_in", "inv_user_id", "inv_user_name",
                "inv_user_email", "inv_user_role",
                "inv_impersonating", "inv_original_user"]:
        st.session_state.pop(key, None)
    st.session_state["app_mode"] = "pipeline"


def require_role(*roles):
    role = st.session_state.get("inv_user_role", "")
    if role not in roles:
        st.warning(f"⛔ This action requires one of: {', '.join(roles)}")
        return False
    return True


def render_login_screen(engine: Engine, dialect: str, fns: dict):
    from modules.file_inventory_governance import (
        authenticate_user, has_any_user, create_user
    )

    # Blue banner — plain string concatenation, no f-string, no CSS braces
    st.markdown(
        "<div style='background:#1A3A6A;border-radius:8px;"
        "padding:16px 20px;margin-bottom:16px;text-align:center;'>"
        "<span style='font-size:1.5rem;font-weight:900;color:#ffffff;'>"
        "Data</span>"
        "<span style='font-size:1.5rem;font-weight:900;color:#FFD700;'>"
        "Wrangler</span><br/>"
        "<span style='font-size:0.8rem;color:rgba(255,255,255,0.8);'>"
        "File Inventory &nbsp;&middot;&nbsp; Data Governance"
        "</span></div>",
        unsafe_allow_html=True
    )

    first_run = not has_any_user(engine, dialect)

    if first_run:
        st.info("👋 No users found. Create the first Manager account.")
        with st.form("inv_register_form"):
            st.subheader("Create Administrator Account")
            name  = st.text_input("Full Name")
            email = st.text_input("Email")
            pw1   = st.text_input("Password",         type="password")
            pw2   = st.text_input("Confirm Password", type="password")
            sub   = st.form_submit_button("Create Account")
            if sub:
                if not all([name, email, pw1, pw2]):
                    st.error("All fields required.")
                elif pw1 != pw2:
                    st.error("Passwords do not match.")
                else:
                    try:
                        create_user(engine, dialect, name, email, pw1,
                                    role="MANAGER", created_by=None)
                        user = authenticate_user(engine, dialect, email, pw1)
                        login(user, engine)
                        st.success("Account created — welcome!")
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))
    else:
        with st.form("inv_login_form"):
            st.subheader("Sign In")
            email = st.text_input("Email")
            pw    = st.text_input("Password", type="password")
            sub   = st.form_submit_button("Sign In")
            if sub:
                user = authenticate_user(engine, dialect, email, pw)
                if user:
                    login(user, engine)
                    st.rerun()
                else:
                    st.error("Invalid credentials or account inactive.")
