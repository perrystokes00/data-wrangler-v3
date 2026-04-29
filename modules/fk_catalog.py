"""
fk_catalog.py  --  PPDM Loader: FK Catalog Reader
Loads the pre-built dialect-specific FK catalog JSON and provides
fast dictionary-based lookups as drop-in replacements for live DB
introspection calls in fk.py.

Files loaded based on dialect:
  schema_registry/ppdm_39_fk_catalog_oracle.json
  schema_registry/ppdm_39_fk_catalog_sqlserver.json

If the catalog file is missing, all functions return None/[] so
callers fall back gracefully to live DB introspection.
"""
from __future__ import annotations
import json, pathlib
from typing import Optional

_BASE = pathlib.Path(__file__).parent.parent / "schema_registry"

def _catalog_path(dialect: str) -> pathlib.Path:
    return _BASE / "ppdm_39_fk_catalog_{}.json".format(dialect.lower())

def _domain_path(dialect: str) -> pathlib.Path:
    return _BASE / "ppdm_39_schema_domain_{}.json".format(dialect.lower())


class FKCatalog:
    """
    Wraps the pre-built FK catalog JSON for a specific dialect.
    Thread-safe for reads.  Call get_catalog(engine) to get the
    right instance for your connected database.
    """

    def __init__(self, dialect: str = "oracle"):
        self._dialect = dialect.lower()
        self._path    = _catalog_path(self._dialect)
        self._data: dict = {}
        self._ok    = False
        self._load()

    def _load(self):
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                self._ok   = True
            else:
                self._ok = False
        except Exception:
            self._data = {}
            self._ok   = False

    def reload(self):
        """Re-read from disk after build_ppdm_catalogs.py runs."""
        self._load()

    @property
    def available(self) -> bool:
        return self._ok and bool(self._data)

    @property
    def dialect(self) -> str:
        return self._data.get("dialect", self._dialect)

    @property
    def built_at(self) -> str:
        return self._data.get("built_at", "")

    # ---- FK constraints ------------------------------------------------

    def get_fk_constraints(self, table_name: str) -> list[dict]:
        if not self._ok: return []
        return self._data.get("fk_constraints", {}).get(table_name.upper(), [])

    def get_parent_tables(self, table_name: str) -> list[str]:
        return list({c["parent_table"] for c in self.get_fk_constraints(table_name)})

    # ---- Primary keys --------------------------------------------------

    def get_pk_cols(self, table_name: str) -> list[str]:
        if not self._ok: return []
        return self._data.get("table_pk", {}).get(table_name.upper(), [])

    # ---- Column metadata -----------------------------------------------

    def get_col_meta(self, table_name: str) -> dict[str, dict]:
        if not self._ok: return {}
        return self._data.get("table_cols", {}).get(table_name.upper(), {})

    def get_col_max_length(self, table_name: str, col_name: str) -> int:
        return self.get_col_meta(table_name).get(col_name.upper(), {}).get("max_length", 0)

    def is_nullable(self, table_name: str, col_name: str) -> bool:
        return self.get_col_meta(table_name).get(col_name.upper(), {}).get("nullable", True)

    def get_not_null_cols(self, table_name: str) -> list[str]:
        return [col for col, info in self.get_col_meta(table_name).items()
                if not info.get("nullable", True)]

    def col_exists(self, table_name: str, col_name: str) -> bool:
        return col_name.upper() in self.get_col_meta(table_name)

    # ---- Table classification ------------------------------------------

    def get_table_kind(self, table_name: str) -> str:
        if not self._ok: return "unknown"
        return self._data.get("table_kind", {}).get(table_name.upper(), "unknown")

    def is_reference_table(self, table_name: str) -> bool:
        return self.get_table_kind(table_name) == "reference"

    def all_tables(self) -> list[str]:
        return list(self._data.get("table_cols", {}).keys())

    # ---- fk.py drop-in replacement ------------------------------------

    def introspect(self, table_name: str, schema: str = "dbo"):
        """
        Return FKIntrospectResult from catalog (no DB round-trip).
        Returns None if table not found -- caller should fall back to
        live DB introspection via fk.introspect_fk_constraints().
        """
        if not self._ok: return None
        constraints_raw = self.get_fk_constraints(table_name)
        if not constraints_raw and table_name.upper() not in self._data.get("table_pk", {}):
            return None

        from modules.fk import FKConstraint, FKColumn, FKIntrospectResult
        constraints = []
        parent_pks: dict[str, list[str]] = {}
        for c in constraints_raw:
            ptbl = c["parent_table"]
            fk_cols = [
                FKColumn(fk_col=cc, ref_col=pc, ordinal=i+1,
                         nullable=self.is_nullable(table_name, cc))
                for i, (cc, pc) in enumerate(zip(c["child_cols"], c["parent_cols"]))
            ]
            constraints.append(FKConstraint(
                constraint_name=c["constraint_name"],
                child_table=table_name.upper(), child_schema=schema,
                parent_table=ptbl, parent_schema=schema, columns=fk_cols,
            ))
            pk_key = "{}.{}".format(schema, ptbl)
            if pk_key not in parent_pks:
                parent_pks[pk_key] = self.get_pk_cols(ptbl)
        return FKIntrospectResult(
            ok=True,
            message="Catalog: {} FK(s) on {}".format(len(constraints), table_name),
            constraints=constraints, parent_pks=parent_pks,
        )

    def parent_row_count_sql(self, table_name: str, schema: str) -> str:
        """
        Build a single UNION ALL query to get live row counts for all
        parent tables of table_name in one DB round-trip.
        Dialect-aware -- uses WITH (NOLOCK) for SQL Server, none for Oracle.
        """
        parents = self.get_parent_tables(table_name)
        if not parents: return ""
        if self._dialect == "oracle":
            parts = [
                "SELECT '{p}' AS tbl, COUNT(*) AS cnt FROM \"{s}\".\"{p}\"".format(p=p, s=schema)
                for p in parents
            ]
        else:
            parts = [
                "SELECT '{p}' AS tbl, COUNT(*) AS cnt FROM [{s}].[{p}] WITH (NOLOCK)".format(p=p, s=schema)
                for p in parents
            ]
        return " UNION ALL ".join(parts)


# ---- Per-dialect singletons ----------------------------------------
_catalogs: dict[str, FKCatalog] = {}

def get_catalog(engine=None, dialect: str = "") -> FKCatalog:
    """
    Return the catalog singleton for the given dialect.
    Pass either an engine (dialect auto-detected) or a dialect string.
    Falls back to oracle if neither is provided.
    """
    if not dialect and engine is not None:
        try:
            from modules.db import _detect_dialect
            dialect = _detect_dialect(engine)
        except Exception:
            dialect = "oracle"
    dialect = (dialect or "oracle").lower()
    if dialect not in _catalogs:
        _catalogs[dialect] = FKCatalog(dialect)
    return _catalogs[dialect]

def reload_catalog(dialect: str = ""):
    """Force reload from disk for a specific dialect (or all if blank)."""
    if dialect:
        dialect = dialect.lower()
        if dialect in _catalogs:
            _catalogs[dialect].reload()
        else:
            _catalogs[dialect] = FKCatalog(dialect)
    else:
        for cat in _catalogs.values():
            cat.reload()
