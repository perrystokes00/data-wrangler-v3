"""
loaders/core/plugin_base.py — Plugin contract.

Each source plugin subclasses SourcePlugin. The runner reads plugins by
the dataclasses they yield (ParsedRow), staging the values to disk and
loading via BCP.

A plugin promises:
  - name and human description
  - native_table name (where source-native columns go)
  - detect(path) → confidence score 0-100 for "this is my kind of file"
  - parse_rows(path) → iterator of ParsedRow
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class ParsedRow:
    """
    The data the runner needs to produce one well's worth of records:

      - uwi: the canonical UWI to use as PK in dv_well and as the foreign
             key to dv_well_ext_*. Plugin-determined (e.g. KGS uses "KGS_<KID>").
      - native_columns: dict {column_name: value} for dv_well_ext_<source>.
             Order is determined by the plugin (must match the ext-table DDL).
      - well_columns: dict {column_name: value} for dv_well (PPDM common shape).
             Missing columns will be NULL.
      - identifiers: list of (identifier_type, identifier_value, is_primary)
             tuples to write to dv_well_identifier. All share one generated
             well_id UNIQUEIDENTIFIER (the runner generates it).
    """
    uwi: str
    native_columns: dict
    well_columns: dict
    identifiers: list[tuple[str, str, bool]] = field(default_factory=list)


@dataclass
class ConfidenceScore:
    """
    Result of plugin.detect(path). The runner picks the highest-scoring
    plugin (or asks the user if multiple tie above the threshold).

      - score:    0-100; >= 80 means "I'm confident", < 50 means "probably not"
      - reason:   short human-readable explanation ("Header matches KGS exactly")
    """
    score: int
    reason: str = ""


class SourcePlugin(ABC):
    """
    Abstract base class for a source plugin.

    Subclasses live in loaders/plugins/<name>.py and are auto-discovered
    by registry.discover().
    """

    #: Short identifier ("KGS", "MI_EGLE", "WY_WOGCC")
    name: str = ""

    #: Human description shown in the UI
    description: str = ""

    #: Fully-qualified destination table for source-native columns
    #: (e.g. "dataview.dv_well_ext_kgs")
    native_table: str = ""

    #: Source label written to dv_well.source (e.g. "KGS")
    source_label: str = ""

    @abstractmethod
    def detect(self, path: Path) -> ConfidenceScore:
        """Return a confidence score that this plugin handles `path`."""
        raise NotImplementedError

    @abstractmethod
    def parse_rows(self, path: Path) -> Iterator[ParsedRow]:
        """
        Yield ParsedRow per source record. Should be a generator
        (streaming) so the runner can process incrementally without
        holding the whole file in memory.
        """
        raise NotImplementedError

    def native_column_order(self) -> list[str]:
        """
        Return the column order for dv_well_ext_<source>. The runner uses
        this to build the staging CSV in the right column order.
        Override in plugin.
        """
        raise NotImplementedError

    def well_column_order(self) -> list[str]:
        """
        Return the column order for dv_well. The runner uses this to build
        the dv_well staging CSV. Plugins should return the canonical
        dv_well column list (defined in cleaning.DV_WELL_COLUMNS).
        """
        from loaders.core.cleaning import DV_WELL_COLUMNS
        return DV_WELL_COLUMNS

    def estimate_row_count(self, path: Path) -> int | None:
        """
        Optional: return an estimated row count for progress reporting.
        Default: line-count the file minus header. Plugins with quoted
        multiline records should override.
        """
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                return sum(1 for _ in f) - 1  # minus header
        except OSError:
            return None
