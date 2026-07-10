Loader hardening: preflight, idempotency, error surfacing, inline H3

Today's KGS load surfaced several brittleness patterns in the loader
that would have hit GoM and the synthetic loader equally hard. Rather
than copy-paste KGS for the next source, fixed the patterns at the
source. End-to-end verified by clean --reload of all 514,713 KGS rows
through the hardened pipeline (preflight → cleanup → parse → 3 BCPs →
LOAD COMPLETE in 5m 46s, with H3 populated inline).

WHY THIS WAS NEEDED
A "dry-run verified" loader hit four real production failures today:
  1. PATH resolved bcp.exe to old Driver 11 (UTF-8 quirks, etc.)
     instead of installed 170.
  2. dv_well.h3_r4 had a NOT NULL constraint added post-design;
     plugin's load-then-backfill flow no longer worked.
  3. When BCP failed, BcpError captured stdout/stderr but never
     printed them — error message was "exit=1" with no diagnosis.
  4. On mid-pipeline failure the runner cleaned up staging files
     in its finally block — so diagnostic remnants vanished.
Plus the loader had no idempotency: a re-run against existing source
data would attempt duplicate inserts and require manual cleanup
between attempts. Recovering from a partial load took ~an hour.

loaders/core/bcp_transport.py
- find_bcp_exe(): searches Microsoft SQL Server Client SDK ODBC dirs
  in newest-first order (180 → 170 → 160 → 150 → 130 → 110), falls
  back to PATH. Caches resolution. Raises FileNotFoundError with
  install guidance on miss.
- bcp_version(): returns "<path> (Version: X.Y.Z)" for preflight
  reporting; best-effort, doesn't fail the load on version-check errors.
- BcpError: __str__ now includes BCP's stdout + stderr verbatim, so
  the actual SQL Server NativeError lines surface automatically.
  Stores the command list for debugging.
- bcp_in(): uses find_bcp_exe() instead of bare "bcp"; accepts
  error_file= param to write rejected rows via BCP -e flag.

loaders/core/runner.py
- New PreflightError exception class.
- RunOptions extended with reload=False, skip_preflight=False.
- _connect(): pyodbc helper with driver-preference fallback
  (Driver 18 → 17 → "SQL Server"). Clear PreflightError on missing
  pyodbc or no driver installed.
- preflight(): 7-step validation runs BEFORE Phase 1 parse:
    (1) source file exists/readable
    (2) bcp.exe locatable
    (3) database connects
    (4) all 3 target tables exist
    (5) column counts match plugin.native_column_order() and
        cleaning.DV_WELL_COLUMNS (positional BCP load requires
        exact column-count alignment)
    (6) h3 library importable (soft check, just informs)
    (7) existing-rows check: refuses if dv_well has rows for this
        source unless --reload was passed
  Each step prints a one-line status. Fails fast with actionable
  PreflightError messages instead of dying 90s into parse.
- _clear_existing_source_rows(): when --reload is set, deletes
  existing dv_well_identifier rows by source_system, dv_well rows
  by source, and truncates the source's ext table. Single
  transaction; rolls back on any error.
- Cleanup-on-failure replaced with cleanup-on-success. On BcpError:
  prints the full error (now with stdout/stderr), lists preserved
  staging file paths AND the .err.txt files BCP wrote rejected rows
  to, and reports which BCPs succeeded before the failure so the user
  knows the partial state. Re-raises so the caller exits with the
  right code.
- run() banner now reports Server/DB, Reload, Skip-preflight.

loaders/run.py
- --reload flag (action=store_true) with destructive warning in help.
- --skip-preflight escape hatch (use only if preflight itself is
  broken).
- Exception handling split: PreflightError → exit 1, no traceback
  (the preflight diagnostic already printed). BcpError → exit 2, no
  traceback (the LOAD FAILED block already printed). KeyboardInterrupt
  → exit 130. Anything else → exit 1 with traceback for debugging.
- Docstring updated with new usage examples and exit codes.

loaders/plugins/kgs.py
- Soft import of h3 (None if unavailable; columns stay NULL).
- New _compute_h3(lat, lon) helper above the class. Returns a dict
  with h3_r4..r7 (H3 cell IDs at resolutions 4/5/6/7) and
  h3_coord_hash (uppercase SHA256 hex of f"{lat}|{lon}" — empirically
  reverse-engineered from existing dv_well rows so the cross-source
  coord-hash join continues to work).
- parse_rows() calls _compute_h3 and populates the 5 h3 keys in
  well_columns. Replaces the "left out — backfill_h3_bcp.py populates
  after load" pattern that was the proximate cause of today's NOT
  NULL violation.

VERIFIED END-TO-END
- First run without --reload: preflight refused with the existing-
  rows message (exit 1, no traceback). All 7 preflight checks fired.
- Second run with --reload:
    - Preflight passed
    - Cleanup: deleted 1,508,319 identifier rows, 514,713 dv_well
      rows, truncated dv_well_ext_kgs (single transaction)
    - Parse: 514,713 rows in 156s (slower than pre-patch 67s due to
      inline H3 computation cost — 514K × 4 H3 lookups + SHA256)
    - BCP dv_well_ext_kgs: 514,713 rows in 36s
    - BCP dv_well: 514,713 rows in 101s (no NOT NULL violation —
      H3 populated inline)
    - BCP dv_well_identifier: 1,508,319 rows in 53s
    - LOAD COMPLETE in 5m 46s
- Data verification: 514,713 / 514,663 with H3 / 514,663 with
  coord_hash. The 50 H3-NULL rows match the 50 null-coord rows from
  file profile. Spot check on KGS_1001184287 confirms inline H3
  matches expected formula.

LESSONS LOGGED
- "Dry-run verified" only exercises parser, not DB-side. A loader
  isn't real until it runs end-to-end against real schema.
- Loaders must locate their own tools (BCP), not trust PATH ordering.
- BCP failures must surface SQL Server's actual error message; an
  exit code by itself is unactionable.
- Schema constraints (NOT NULL especially) drift independently of
  loader code. Preflight column-count check catches the biggest
  class of mismatches.
- Multi-step pipelines need either all-or-nothing transactions OR
  idempotent steps. The current pattern: idempotent via --reload,
  with per-BCP error files for diagnostics.
- Staging cleanup should happen on success only. On failure those
  files ARE the diagnostic.
- Long-running SSMS transactions left uncommitted block subsequent
  reads of the affected table; preflight's existing-rows check
  appears to "hang" when this happens. Worth a future enhancement:
  detect blocked sessions in preflight.
