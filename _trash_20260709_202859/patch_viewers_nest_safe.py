r"""
patch_viewers_nest_safe.py — make file_viewer's per-format viewers nest-safe by
replacing st.expander(...) with a bordered container + caption. Expanders can't be
nested inside other expanders (Streamlit raises), which breaks these viewers when
called from an embedding context (e.g. the Documents page's per-entity expanders).
A bordered container gives the same visual section grouping but nests anywhere.

Transforms:  with st.expander("Label", expanded=True):  ->  _section("Label"):
where _section is a tiny helper (added to the module) that opens a bordered
container and writes the label. `expanded=` is dropped (containers are always shown;
that's fine — the sections were mostly expanded=True anyway; the one collapsed
section, docx Tables, becomes shown but that's acceptable inside the viewer).

In place, .bak, idempotent. py patch_viewers_nest_safe.py
"""
import sys, os, re, ast
P = "file_viewer.py"
if not os.path.exists(P):
    sys.exit("file_viewer.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "_vsection" in s:
    print("already patched"); sys.exit(0)

# 1) add the helper after the imports / before the first def
helper = '''
from contextlib import contextmanager as _contextmanager

@_contextmanager
def _vsection(label: str):
    """Nest-safe replacement for st.expander in embeddable viewers: a bordered
    container with a bold label. Unlike expander, containers can be nested inside
    an expander (so these viewers work when embedded in the Documents page)."""
    import streamlit as st
    box = st.container(border=True)
    with box:
        if label:
            st.markdown(f"**{label}**")
        yield box

'''
# insert right after the `def view(` dispatcher's module-level imports; simplest:
# put it immediately before the first "def _view_" definition.
m = re.search(r"\ndef _view_", s)
if not m:
    sys.exit("no _view_ functions found")
s = s[:m.start()] + "\n" + helper + s[m.start():]

# 2) replace every `with st.expander("X", expanded=Y):` (and multiline variants)
#    with `with _vsection("X"):`. Handle both single-line and wrapped forms.
# single-line
s = re.sub(r'with st\.expander\(\s*("(?:[^"\\]|\\.)*"|f"(?:[^"\\]|\\.)*")\s*,\s*expanded\s*=\s*(?:True|False)\s*\)\s*:',
           r'with _vsection(\1):', s)
# f-string label with parens inside, single line already covered; also handle
# labels with no expanded= (rare) :
s = re.sub(r'with st\.expander\(\s*("(?:[^"\\]|\\.)*"|f"(?:[^"\\]|\\.)*")\s*\)\s*:',
           r'with _vsection(\1):', s)

# 3) handle the one multiline expander in _view_segy (line ~449): expander( \n ...)
#    Replace any remaining `st.expander(` occurrences conservatively by collapsing
#    to _vsection with the first string arg.
def _collapse_multiline(src):
    out = src
    pat = re.compile(r'with st\.expander\((.*?)\)\s*:', re.DOTALL)
    def repl(mm):
        inner = mm.group(1)
        # grab first quoted string (label)
        lm = re.search(r'(f?"(?:[^"\\]|\\.)*")', inner, re.DOTALL)
        label = lm.group(1) if lm else '""'
        # flatten any newlines in the label
        label = re.sub(r'\s*\n\s*', ' ', label)
        return f'with _vsection({label}):'
    return pat.sub(repl, out)
s = _collapse_multiline(s)

remaining = s.count("st.expander(")
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: expanders -> nest-safe _vsection ({remaining} st.expander refs left)")
