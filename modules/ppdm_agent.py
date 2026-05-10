"""
ppdm_agent.py  —  PPDM Loader · AI Assistant
=============================================
Wraps the Anthropic API to provide a PPDM-aware chat agent.
Reads ANTHROPIC_API_KEY from .env in the project root.

Usage (from app.py):
    from modules.ppdm_agent import PPDMAgent, build_pipeline_context
    agent = PPDMAgent()
    reply = agent.chat(messages, pipeline_ctx)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Load .env ──────────────────────────────────────────────────────────────
def _load_env() -> str:
    """Try multiple locations for .env, return the path found or empty string."""
    import os.path as _osp
    candidates = [
        _osp.join(_osp.dirname(_osp.dirname(_osp.abspath(__file__))), ".env"),
        _osp.join(_osp.dirname(_osp.abspath(__file__)), ".env"),
        _osp.join(os.getcwd(), ".env"),
        _osp.join(_osp.dirname(os.getcwd()), ".env"),
    ]
    for env_path in candidates:
        if _osp.isfile(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return env_path
    return ""

_ENV_PATH = _load_env()


# ── PPDM Domain Knowledge ──────────────────────────────────────────────────
PPDM_SYSTEM_PROMPT = """You are an expert PPDM (Professional Petroleum Data Management) \
data model assistant embedded in a PPDM 3.9 data loader application.

## Your Role
Help users understand the PPDM 3.9 relational data model and guide them on how to \
correctly load petroleum industry data. You understand table relationships, foreign key \
dependencies, and the correct order for loading data.

## PPDM 3.9 Core Table Groups & Load Order

### Reference Tables (load first — no FK dependencies on entity tables)
All tables prefixed `r_` or `ra_` are reference/lookup tables.
Examples: r_well_class, r_well_status, r_source, r_ppdm_row_quality,
r_strat_type, r_dir_srvy_type, r_well_node_type

### Business Associate & Location (load early)
1. business_associate — companies, regulators, operators
2. area, area_hierarchy — geographic areas
3. field — petroleum fields

### Well Header (core entity)
4. well — master well record (UWI is primary key)
   FK dependencies: business_associate, area, field, r_well_class, r_well_status,
   r_well_type, r_source, strat_unit (optional strat picks)

### Well Nodes / Geometry
5. well_node — surface and bottom-hole locations
   FK: well
6. well_node_survey — node position details
   FK: well_node

### Directional Surveys (load in this exact order)
7. well_dir_srvy — directional survey header
   FK: well, business_associate, r_dir_srvy_type, r_source
8. well_dir_srvy_station — individual survey stations (MD, incl, azimuth)
   FK: well_dir_srvy (PARENT — must exist first), well

### Stratigraphy (load in this exact order)
9. strat_name_set — stratigraphic naming system (e.g. KANSAS_LEXICON)
10. strat_unit — formation/unit names
    FK: strat_name_set (compound PK: STRAT_NAME_SET_ID + STRAT_UNIT_ID)
11. strat_well_section — strat picks per well
    FK: well, strat_unit, strat_name_set
    PK: UWI + STRAT_NAME_SET_ID + STRAT_UNIT_ID + INTERP_ID
    Note: source data is often WIDE format (BASE_STRAT_NAME_SET_ID, TD_STRAT_NAME_SET_ID
    etc.) and must be PIVOTED to long format before loading. INTERP_ID = pick type
    (BASE, TD, TOP, OLDEST, CONFID etc.)

### Well Logs
12. well_log — log header
    FK: well, business_associate
13. well_log_curve — individual curves
    FK: well_log (must exist first)

### Production
14. prod_string — production string/completion
    FK: well
15. prod_string_formation — formation intervals
    FK: prod_string

### Facility
16. facility — surface facility
    FK: business_associate, area

## Foreign Key Rules
- Always load PARENT tables before CHILD tables
- Reference tables (r_*) are always parents — load them first via the Reference Table Manager
- Compound PKs (e.g. strat_unit) require ALL PK columns to be populated
- The app's FK Resolution stage shows you exactly which parent rows are missing
- Use the Seed Catalog tool to populate reference tables in bulk

## Common Load Sequences

### Directional Survey Load Order:
1. r_dir_srvy_type (ref table — seed or RTM)
2. r_source (ref table)
3. business_associate (if new operators)
4. well (must exist)
5. well_dir_srvy (survey header)
6. well_dir_srvy_station (stations — one row per depth point)

### Strat Load Order:
1. Reference tables: r_strat_type, r_strat_name_set_type, r_source
2. strat_name_set (entity — use RTM manual entry)
3. strat_unit (entity — use RTM, compound PK)
4. strat_well_section (use pivot script to convert wide→long first)

### Basic Well Header Load Order:
1. All r_* reference tables for well columns
2. business_associate
3. area / field (if used)
4. well

## Data Quality Notes
- UWI (Unique Well Identifier) format: varies by jurisdiction
- Dates should be ISO format (YYYY-MM-DD) before loading
- All indicator columns (ACTIVE_IND, PREFERRED_IND) should be 'Y' or 'N'
- PPDM_GUID, ROW_CREATED_DATE etc. are auto-generated by the loader
- SOURCE column should reference a valid r_source code

## This Application
The PPDM Loader app has 8 stages:
1. Connect — connect to SQL Server
2. Upload & Stage — upload CSV/Excel, load to staging table
3. Normalize — trim, uppercase indicators, standardize dates
4. Select Target — choose the PPDM target table
5. Match & Map — map source columns to PPDM columns
6. FK Resolution — resolve foreign key violations
7. Validate — run data quality checks
8. Promote — INSERT data into the target PPDM table

Tools available in the sidebar:
- Reference Table Manager (RTM) — manually insert/upload rows to any table
- Seed Catalog — bulk-populate reference tables
- PPDM Data Model Viewer — browse the 198-page ER diagram PDF
- This assistant

Always be specific and actionable. When asked about load order, list the exact tables
in sequence. When asked about a specific table, describe its key columns and FK parents.
"""


# ── Pipeline context builder ───────────────────────────────────────────────
def build_pipeline_context(S) -> str:
    """Build a concise string describing the current pipeline state."""
    parts = []

    stage_names = [
        "Connect", "Upload & Stage", "Normalize", "Select Target",
        "Match & Map", "FK Resolution", "Validate", "Promote"
    ]
    stage = getattr(S, "stage", 0)
    stage_name = stage_names[stage] if stage < len(stage_names) else "Unknown"
    parts.append(f"Current stage: {stage} · {stage_name}")

    if getattr(S, "target_table", None):
        parts.append(f"Target table: {S.target_table}")

    if getattr(S, "col_mapping", None):
        try:
            mapped = [m.ppdm_col for m in S.col_mapping.mapped
                      if not getattr(m, "auto_generated", False)]
            if mapped:
                parts.append(f"Mapped columns ({len(mapped)}): {', '.join(mapped[:10])}"
                             + ("…" if len(mapped) > 10 else ""))
        except Exception:
            pass

    if getattr(S, "fk_violations", None):
        viols = S.fk_violations
        unresolved = [v for v in viols
                      if not getattr(v, "resolved", False)]
        if unresolved:
            tables = list({v.constraint.parent_table for v in unresolved})
            parts.append(f"Unresolved FK violations — parent tables needed: "
                         f"{', '.join(tables[:5])}"
                         + ("…" if len(tables) > 5 else ""))

    if getattr(S, "fk_graph", None):
        graph = S.fk_graph
        dep_tables = [n.table_name for n in graph
                      if not n.table_name.lower().startswith(("r_", "ra_"))]
        if dep_tables:
            parts.append(f"FK dependency graph — entity parents: "
                         f"{', '.join(dep_tables[:8])}"
                         + ("…" if len(dep_tables) > 8 else ""))

    if getattr(S, "stg_table", None):
        parts.append(f"Staging table: {getattr(S, 'stg_schema', 'stg')}.{S.stg_table}")

    return "\n".join(parts) if parts else "No active pipeline session."


# ── Agent ──────────────────────────────────────────────────────────────────
@dataclass
class PPDMAgent:
    model:       str   = "claude-sonnet-4-6"
    max_tokens:  int   = 1024
    _client:     object = field(default=None, repr=False)

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if not api_key:
                    raise ValueError(
                        "ANTHROPIC_API_KEY not found. Add it to your .env file:\n"
                        "ANTHROPIC_API_KEY=sk-ant-..."
                    )
                self._client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                raise ImportError(
                    "anthropic package not installed.\n"
                    "Run: pip install anthropic python-dotenv"
                )
        return self._client

    def chat(
        self,
        messages:     list[dict],   # [{"role": "user"/"assistant", "content": str}]
        pipeline_ctx: str = "",
    ) -> str:
        """Send messages and return the assistant reply text."""
        client = self._get_client()

        system = PPDM_SYSTEM_PROMPT
        if pipeline_ctx:
            system += f"\n\n## Current Pipeline Context\n{pipeline_ctx}"

        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
        )
        return response.content[0].text

    def is_configured(self) -> tuple[bool, str]:
        """Check if API key is available. Returns (ok, message)."""
        found_path = _load_env()
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            # Show every candidate and whether it exists
            import os.path as _osp
            candidates = [
                _osp.join(_osp.dirname(_osp.dirname(_osp.abspath(__file__))), ".env"),
                _osp.join(_osp.dirname(_osp.abspath(__file__)), ".env"),
                _osp.join(os.getcwd(), ".env"),
                _osp.join(_osp.dirname(os.getcwd()), ".env"),
            ]
            details = "\n".join(
                f"  {'✓' if _osp.isfile(p) else '✗'} {p}" for p in candidates)
            return False, f"ANTHROPIC_API_KEY not set.\nSearched:\n{details}"
        if not key.startswith("sk-"):
            return False, f"Key found but looks invalid (starts with: {key[:8]}…)"
        try:
            import anthropic  # noqa
            return True, "Ready"
        except ImportError:
            return False, "anthropic not installed — run: pip install anthropic python-dotenv"
