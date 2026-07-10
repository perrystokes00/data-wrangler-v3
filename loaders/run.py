"""
loaders/run.py — Command-line entry point.

Usage:
  python -m loaders.run --list                    # show all plugins
  python -m loaders.run --detect FILE             # show detection scores
  python -m loaders.run --plugin KGS --file FILE  # explicit plugin
  python -m loaders.run --file FILE               # auto-detect best plugin
  python -m loaders.run --file FILE --dry-run     # parse only, no DB write
  python -m loaders.run --plugin KGS --file FILE --reload
                                                  # destructive re-load:
                                                  # clears existing source
                                                  # rows from dv_well,
                                                  # dv_well_ext_<src>, and
                                                  # dv_well_identifier first

Exit codes:
  0 — success
  1 — usage error, plugin not found, source file missing, or preflight fail
  2 — BCP failure during load (staging preserved for inspection)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loaders.core import registry
from loaders.core.bcp_transport import BcpError
from loaders.core.runner import PreflightError, RunOptions, run


def main() -> int:
    ap = argparse.ArgumentParser(description="Data Wrangler source loader")
    ap.add_argument("--list", action="store_true",
                    help="List available plugins and exit")
    ap.add_argument("--detect", metavar="FILE",
                    help="Show detection scores for FILE and exit")
    ap.add_argument("--plugin", metavar="NAME",
                    help="Force a specific plugin by name (e.g. KGS)")
    ap.add_argument("--file", metavar="FILE",
                    help="Source file to load")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse + stage but do not BCP into DB. Also skips "
                         "preflight (which would need DB connection).")
    ap.add_argument("--skip-bcp", action="store_true",
                    help="Write staging CSVs but skip BCP step")
    ap.add_argument("--keep-staging", action="store_true",
                    help="Don't delete staging CSVs after load")
    ap.add_argument("--reload", action="store_true",
                    help="DESTRUCTIVE: clear existing rows for this source "
                         "from dv_well, dv_well_ext_<src>, and "
                         "dv_well_identifier before loading. Required when "
                         "the source already has rows in dv_well.")
    ap.add_argument("--skip-preflight", action="store_true",
                    help="Skip the Phase 0 preflight checks (table existence, "
                         "column-count alignment, BCP location, etc). "
                         "Not recommended — preflight catches problems in "
                         "seconds that would otherwise surface 90s into "
                         "parse. Use only if preflight is itself broken.")
    args = ap.parse_args()

    # --list
    if args.list:
        plugins = registry.get_all()
        if not plugins:
            print("No plugins discovered.")
            return 1
        print(f"Available plugins ({len(plugins)}):")
        for p in plugins:
            print(f"  {p.name:<15} — {p.description}")
        return 0

    # --detect
    if args.detect:
        path = Path(args.detect)
        if not path.exists():
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            return 1
        print(f"Detection results for: {path}")
        print()
        for plugin, score in registry.detect_best(path):
            marker = "✓" if score.score >= 80 else ("?" if score.score >= 50 else " ")
            print(f"  {marker} {plugin.name:<15} {score.score:>3}%  {score.reason}")
        return 0

    # Run mode: need a file
    if not args.file:
        ap.error("--file is required (or use --list / --detect)")

    path = Path(args.file)
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1

    # Plugin selection
    if args.plugin:
        plugin = registry.get_by_name(args.plugin)
        if not plugin:
            print(f"ERROR: no plugin named '{args.plugin}'", file=sys.stderr)
            print("Available:", file=sys.stderr)
            for p in registry.get_all():
                print(f"  {p.name}", file=sys.stderr)
            return 1
    else:
        # Auto-detect best
        ranked = registry.detect_best(path)
        if not ranked or ranked[0][1].score < 50:
            print(f"ERROR: no plugin confident enough to handle {path}", file=sys.stderr)
            print("Detection scores:", file=sys.stderr)
            for p, s in ranked:
                print(f"  {p.name:<15} {s.score:>3}%  {s.reason}", file=sys.stderr)
            print("Try --plugin NAME to force a choice.", file=sys.stderr)
            return 1
        plugin, score = ranked[0]
        print(f"Auto-detected plugin: {plugin.name} ({score.score}%) — {score.reason}")
        print()

    # Run the load
    options = RunOptions(
        dry_run=args.dry_run,
        skip_bcp=args.skip_bcp,
        keep_staging=args.keep_staging,
        reload=args.reload,
        skip_preflight=args.skip_preflight,
    )
    try:
        run(plugin, path, options)
    except PreflightError:
        # Preflight printed its own diagnostic message; no traceback needed
        return 1
    except BcpError:
        # Runner already printed the LOAD FAILED block with details and
        # staging-file paths; no traceback needed
        return 2
    except KeyboardInterrupt:
        print("\nAborted by user.", file=sys.stderr)
        return 130
    except Exception as e:
        # Unexpected — keep the traceback for these so we can fix them
        print(f"\nLOAD FAILED (unexpected): {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
