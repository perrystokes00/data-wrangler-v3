"""
loaders/core/stats.py — Load progress and result statistics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time


@dataclass
class LoadStats:
    """
    Per-load statistics. Plugins update during parse; the runner updates
    BCP rowcounts and timing.
    """
    # Parse phase
    rows_read:           int = 0
    rows_rejected:       int = 0
    rows_accepted:       int = 0
    duplicate_uwis:      int = 0
    reject_reasons:      dict = field(default_factory=dict)

    # Data quality counters
    rows_with_coords:    int = 0
    rows_without_coords: int = 0
    rows_with_api:       int = 0
    rows_with_operator:  int = 0
    rows_with_field:     int = 0

    # BCP load phase
    bcp_rows_loaded:     dict = field(default_factory=dict)  # table → rowcount
    bcp_elapsed:         dict = field(default_factory=dict)  # table → seconds

    # Timing
    parse_start:         float = 0.0
    parse_end:           float = 0.0
    load_start:          float = 0.0
    load_end:            float = 0.0

    def reject(self, reason: str) -> None:
        self.rows_rejected += 1
        self.reject_reasons[reason] = self.reject_reasons.get(reason, 0) + 1

    @property
    def parse_seconds(self) -> float:
        return self.parse_end - self.parse_start if self.parse_end else 0.0

    @property
    def load_seconds(self) -> float:
        return self.load_end - self.load_start if self.load_end else 0.0

    @property
    def total_seconds(self) -> float:
        return self.parse_seconds + self.load_seconds

    def summary_lines(self) -> list[str]:
        """Return a list of human-readable summary lines."""
        lines = [
            f"Rows read              : {self.rows_read:,}",
            f"Rows accepted          : {self.rows_accepted:,}",
            f"Rows rejected          : {self.rows_rejected:,}",
            f"Duplicate UWIs skipped : {self.duplicate_uwis:,}",
        ]
        if self.reject_reasons:
            lines.append("  Reject reasons:")
            for reason, n in sorted(
                self.reject_reasons.items(), key=lambda x: -x[1]
            ):
                lines.append(f"    {reason:<40} {n:,}")
        lines.append("")
        lines.append(
            f"With coords            : {self.rows_with_coords:,}"
        )
        lines.append(
            f"With API               : {self.rows_with_api:,}"
        )
        lines.append(
            f"With operator          : {self.rows_with_operator:,}"
        )
        lines.append(
            f"With field name        : {self.rows_with_field:,}"
        )
        if self.bcp_rows_loaded:
            lines.append("")
            lines.append("BCP results:")
            for table, n in self.bcp_rows_loaded.items():
                t = self.bcp_elapsed.get(table, 0.0)
                lines.append(f"  {table:<35} {n:>10,} rows in {t:.1f}s")
        lines.append("")
        lines.append(f"Parse elapsed          : {self.parse_seconds:.1f}s")
        lines.append(f"Load elapsed           : {self.load_seconds:.1f}s")
        lines.append(f"Total                  : {self.total_seconds:.1f}s")
        return lines
