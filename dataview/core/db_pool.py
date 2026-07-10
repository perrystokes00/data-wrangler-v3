"""
db_pool.py — PPDM Loader: Module-level engine singleton
========================================================
Streamlit drops SQLAlchemy engine objects from session state between reruns.
This module holds the engine at the Python process level — it persists as long
as the Streamlit server is running.

Usage:
    from dataview.core.db_pool import set_engine, get_engine, clear_engine
    set_engine(result.engine, "snowflake")
    engine = get_engine()
"""

from __future__ import annotations
from typing import Optional

_engine = None
_dialect: str = ""


def set_engine(engine, dialect: str = "") -> None:
    """Store engine at module level."""
    global _engine, _dialect
    _engine  = engine
    _dialect = dialect.lower()


def get_engine():
    """Return the stored engine, or None if not set."""
    return _engine


def get_dialect() -> str:
    """Return the stored dialect name."""
    return _dialect


def clear_engine() -> None:
    """Clear the stored engine (on disconnect/reset)."""
    global _engine, _dialect
    _engine  = None
    _dialect = ""


def has_engine() -> bool:
    """True if an engine is stored."""
    return _engine is not None
