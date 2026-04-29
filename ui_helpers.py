"""
ui_helpers.py — Shared UI helper functions for page modules.
Import this in each page module.
"""
import streamlit as st


def shdr(title, desc=""):
    st.markdown(f'<div class="shdr"><h3>{title}</h3>'
                + (f'<p>{desc}</p>' if desc else '') + '</div>',
                unsafe_allow_html=True)


def pill(text, cls="p-opt"):
    return f'<span class="pill {cls}">{text}</span>'


def mrow(items):
    cols = st.columns(len(items))
    for c, (lbl, val, color) in zip(cols, items):
        c.markdown(f'<div class="mbox"><div class="v" style="color:{color}">{val}</div>'
                   f'<div class="l">{lbl}</div></div>', unsafe_allow_html=True)


def go(S):
    S.stage += 1
    st.rerun()


def back(S):
    S.stage = max(0, S.stage - 1)
    st.rerun()


def reset(S, DEFAULTS):
    for k, v in DEFAULTS.items():
        S[k] = v
    st.rerun()
