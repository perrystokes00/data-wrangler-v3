"""
loaders/core/bcp_transport.py — BCP staging CSV writer and BCP runner.

The pattern (proven in Session 4):
  1. Write a CSV with | as field separator and \\n as row terminator
  2. Run `bcp <table> in <file>` with -c -t| -C 65001 -T -k -m 10
  3. Parse 'N rows copied' from BCP stdout

All values must be pre-cleaned by the plugin: no embedded newlines, no
pipes, no tabs in field values. cleaning.clean_text() handles this.

2026-05-28 hardening:
  - find_bcp_exe() locates the newest BCP on the system rather than
    trusting PATH (which can resolve to a stale Driver 11 BCP).
  - BcpError now prints stdout and stderr when raised so the actual
    SQL Server error message is visible (the previous behavior swallowed
    it and reported only "exit=1").
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable, Optional

FIELD_SEP = "|"
ROW_SEP   = "\n"


# -----------------------------------------------------------------------------
# BCP executable location
# -----------------------------------------------------------------------------
# Search order for bcp.exe. We prefer the newest available driver (170 = ODBC
# 17, 180 = ODBC 18) because older drivers (110/130) have known issues with
# UTF-8 (-C 65001), datetime2 conversions, and long strings. The actual
# driver bound to a given bcp.exe is determined by which Microsoft SQL Server
# Client SDK directory it was installed under.
_BCP_SEARCH_DIRS_WINDOWS = [
    # Modern Microsoft Command Line Utilities install path
    r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\180\Tools\Binn",
    r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn",
    r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\160\Tools\Binn",
    r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\150\Tools\Binn",
    # Older SQL Server-bundled BCPs (Driver 11 — known to misbehave with
    # UTF-8 and certain conversions; listed last as a fallback only).
    r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\130\Tools\Binn",
    r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\110\Tools\Binn",
]

# Resolved once per process. Used by bcp_in().
_resolved_bcp: Optional[Path] = None


def find_bcp_exe() -> Path:
    """
    Locate the newest available bcp.exe on the system.

    Searches a known list of Microsoft SQL Server install directories in
    descending driver-version order, falls back to PATH lookup, and finally
    to a bare 'bcp' command (which may or may not resolve at exec time).

    Raises FileNotFoundError if no bcp executable can be located.

    Cached on first call; rerun the process to re-detect.
    """
    global _resolved_bcp
    if _resolved_bcp is not None:
        return _resolved_bcp

    # Windows: try the standard SDK locations in preferred-version order
    if os.name == "nt":
        for d in _BCP_SEARCH_DIRS_WINDOWS:
            candidate = Path(d) / "bcp.exe"
            if candidate.exists():
                _resolved_bcp = candidate
                return candidate

    # Fallback: PATH lookup (which-style)
    fallback = shutil.which("bcp") or shutil.which("bcp.exe")
    if fallback:
        _resolved_bcp = Path(fallback)
        return _resolved_bcp

    raise FileNotFoundError(
        "bcp executable not found. Tried Microsoft SQL Server Client SDK "
        "directories under C:\\Program Files\\Microsoft SQL Server\\Client SDK\\ODBC\\<ver>"
        "\\Tools\\Binn, and PATH. Install the Microsoft Command Line "
        "Utilities for SQL Server, or ensure bcp.exe is on PATH."
    )


def bcp_version() -> str:
    """
    Return a one-line description of the bcp version that will be used.
    Useful for preflight reporting. Best-effort — returns 'unknown' on error.
    """
    try:
        exe = find_bcp_exe()
    except FileNotFoundError as e:
        return f"NOT FOUND ({e})"
    try:
        result = subprocess.run(
            [str(exe), "-v"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        # bcp -v prints something like:
        #   BCP - Bulk Copy Program for Microsoft SQL Server.
        #   Copyright (C) ...
        #   Version: 17.10.6.1
        for line in (result.stdout or "").splitlines():
            if "Version:" in line:
                return f"{exe} ({line.strip()})"
        return f"{exe}"
    except Exception as e:
        return f"{exe} (version check failed: {e})"


# -----------------------------------------------------------------------------
# Staging directory management
# -----------------------------------------------------------------------------
def get_staging_dir(name: str = "dw_load") -> Path:
    """
    Return a staging directory under %LOCALAPPDATA%\\Temp (or /tmp on linux).
    Created if missing.
    """
    base = Path(os.environ.get("LOCALAPPDATA", "/tmp"))
    sd = base / "Temp" / name
    sd.mkdir(parents=True, exist_ok=True)
    return sd


def cleanup_staging(*paths: Path) -> None:
    """Delete the given staging files, ignoring missing-file errors."""
    for p in paths:
        try:
            p.unlink()
        except FileNotFoundError:
            pass


# -----------------------------------------------------------------------------
# CSV writer
# -----------------------------------------------------------------------------
class BcpCsvWriter:
    """
    Writes a BCP-compatible CSV using FIELD_SEP/ROW_SEP. None values become
    empty fields; BCP -k flag tells BCP to treat empty as NULL.

    Values must NOT contain FIELD_SEP or ROW_SEP — the plugin is responsible
    for stripping these (use cleaning.clean_text()).

    Usage:
        w = BcpCsvWriter(Path("staging.csv"))
        w.write_row(["uwi-123", "Well A", None, 42])
        w.close()  # returns rowcount
    """
    def __init__(self, path: Path):
        self.path = path
        self.f = path.open("w", encoding="utf-8", newline="")
        self.n = 0

    def write_row(self, values: Iterable) -> None:
        out = []
        for v in values:
            if v is None:
                out.append("")
            else:
                # Defensive: even if the plugin slipped, strip newlines+pipes
                s = str(v)
                if FIELD_SEP in s or "\n" in s or "\r" in s:
                    s = s.replace(FIELD_SEP, " ").replace("\n", " ").replace("\r", " ")
                out.append(s)
        self.f.write(FIELD_SEP.join(out))
        self.f.write(ROW_SEP)
        self.n += 1

    def close(self) -> int:
        self.f.close()
        return self.n


# -----------------------------------------------------------------------------
# BCP runner
# -----------------------------------------------------------------------------
class BcpError(Exception):
    """
    Raised when BCP returns a non-zero exit code OR when BCP exits 0 but
    copied 0 rows (a common silent-failure mode).

    The error's str() output includes BCP's stdout and stderr verbatim
    so the user sees the actual SQL Server NativeError / SQLState lines
    that explain what went wrong. Prior versions stored these but didn't
    surface them, leaving callers staring at "exit=1" with no diagnosis.
    """
    def __init__(self, table: str, exit_code: int, stdout: str, stderr: str,
                 cmd: list[str] | None = None):
        self.table = table
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.cmd = cmd or []
        # Build a detailed message. Surface stderr first (where SQL Server
        # error messages live), then stdout (which includes BCP's per-batch
        # row-count summary if anything got copied before failing).
        parts = [f"BCP into {table} failed (exit={exit_code})"]
        if stderr.strip():
            parts.append("--- BCP stderr ---")
            parts.append(stderr.rstrip())
        if stdout.strip():
            parts.append("--- BCP stdout ---")
            parts.append(stdout.rstrip())
        super().__init__("\n".join(parts))


def bcp_in(
    csv_path: Path,
    table_fqn: str,
    server: str,
    database: str,
    max_errors: int = 10,
    error_file: Path | None = None,
) -> tuple[int, float]:
    """
    Run `bcp <table_fqn> in <csv_path>` with our standard flags.

    Uses find_bcp_exe() to resolve the BCP executable so we get a modern
    driver version regardless of PATH order.

    `error_file` (optional): if provided, BCP writes rejected rows to it
    via -e flag — invaluable for diagnosing per-row failures.

    Returns (rows_copied, elapsed_seconds).
    Raises BcpError on non-zero exit code (with stdout/stderr in the
    message) OR on 0-rows-copied-with-exit-0 (silent failure).
    """
    bcp_exe = find_bcp_exe()
    cmd = [
        str(bcp_exe), table_fqn, "in", str(csv_path),
        "-c",
        "-t", FIELD_SEP,
        "-r", "0x0a",  # hex-encoded LF — '\\n' literal is not reliably interpreted on Windows BCP
        "-C", "65001",
        "-T",
        f"-S{server}",
        f"-d{database}",
        "-k",
        "-q",          # QUOTED_IDENTIFIER ON — required for filtered/computed indexes
        "-m", str(max_errors),
    ]
    if error_file is not None:
        cmd += ["-e", str(error_file)]

    t0 = time.time()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.time() - t0

    if result.returncode != 0:
        raise BcpError(
            table=table_fqn,
            exit_code=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            cmd=cmd,
        )

    # Parse "N rows copied"
    rows = 0
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if "rows copied" in line.lower():
            try:
                rows = int(line.split()[0].replace(",", ""))
            except (ValueError, IndexError):
                pass
            break

    # Defensive: BCP can return exit code 0 while loading 0 rows
    if rows == 0:
        raise BcpError(
            table=table_fqn,
            exit_code=0,
            stdout=result.stdout or "",
            stderr=(result.stderr or "") +
                   "\n(0 rows copied with exit 0 — likely row-terminator or column-count mismatch)",
            cmd=cmd,
        )

    return rows, elapsed
