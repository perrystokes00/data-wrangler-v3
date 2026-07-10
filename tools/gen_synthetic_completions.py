"""
gen_synthetic_completions.py
─────────────────────────────────────────────────────────────────────────────
Recreate dv_well_completion + dv_well_stimulation with an IMPROVED completions
model and load realistic, play-aware synthetic data for a list of wells.

Why a new model
  • dv_well_completion becomes a rich completion *header* (orientation, lateral
    length, completion design, frac fluid system, proppant type, and rollups:
    stage_count / total_fluid_bbl / total_proppant_lbs / intensities).
  • dv_well_stimulation becomes ONE ROW PER FRAC STAGE (the real fix) — the old
    table only stored a flat stage_count and could not represent stages.

Usage
  python gen_synthetic_completions.py --dry-run          # generate + print, no DB
  python gen_synthetic_completions.py --sample 5000      # N random wells, play-aware
  python gen_synthetic_completions.py                    # the default UWI list
  python gen_synthetic_completions.py --uwi-file uwis.txt

Notes
  • RECREATE drops and rebuilds BOTH tables (synthetic data only — safe).
  • Bulk load via SQLAlchemy fast_executemany (no per-row SQL loops).
"""
import argparse
import datetime as dt
import random

import numpy as np
import pandas as pd

# ── config ──────────────────────────────────────────────────────────────────
SERVER   = r"localhost\SQLEXPRESS"
DATABASE = "DataView"
SCHEMA   = "dataview"
SEED     = 42

# default well list (the 7 unique UWIs supplied; duplicates collapsed)
DEFAULT_UWIS = [
    "US42100000090000", "US42141000360000", "US42208000050000",
    "US42254000430000", "US42447000270000", "US42468000080000",
    "US42482000170000",
]

HORIZONTAL_FRACTION = 0.70   # share of wells completed as horizontal multistage

# Play profiles keyed by state — horizontal/vertical formation pools, gas bias.
PLAYS = {
    "TEXAS": dict(h=["Wolfcamp A", "Wolfcamp B", "Wolfcamp C", "Spraberry",
                     "Lower Spraberry", "Bone Spring 2nd", "Bone Spring 3rd",
                     "Dean", "Eagle Ford", "Austin Chalk", "Cline"],
                  v=["San Andres", "Grayburg", "Clearfork", "Canyon", "Strawn",
                     "Devonian", "Ellenburger", "Yates"]),
    "NEW MEXICO": dict(h=["Wolfcamp A", "Wolfcamp B", "Bone Spring 1st",
                          "Bone Spring 2nd", "Bone Spring 3rd", "Avalon"],
                       v=["San Andres", "Grayburg", "Yeso", "Abo"]),
    "NORTH DAKOTA": dict(h=["Middle Bakken", "Three Forks 1", "Three Forks 2"],
                         v=["Madison", "Red River", "Mission Canyon"]),
    "OKLAHOMA": dict(h=["Woodford", "Meramec", "Osage", "Sycamore"],
                     v=["Hunton", "Mississippian", "Springer", "Morrow"]),
    "COLORADO": dict(h=["Niobrara A", "Niobrara B", "Niobrara C", "Codell"],
                     v=["J Sand", "D Sand", "Muddy"]),
    "WYOMING": dict(h=["Niobrara", "Mowry", "Turner", "Parkman"],
                    v=["Frontier", "Muddy", "Tensleep"]),
    "PENNSYLVANIA": dict(h=["Marcellus", "Utica", "Point Pleasant"],
                         v=["Oriskany", "Medina"], gas=True),
    "WEST VIRGINIA": dict(h=["Marcellus", "Utica"], v=["Oriskany"], gas=True),
    "LOUISIANA": dict(h=["Haynesville", "Bossier"],
                      v=["Cotton Valley", "Austin Chalk"], gas=True),
    "KANSAS": dict(h=["Mississippian", "Cherokee"],
                   v=["Lansing-Kansas City", "Arbuckle", "Morrow"]),
    "MICHIGAN": dict(h=["Antrim", "Collingwood"],
                     v=["Niagaran", "Prairie du Chien", "Trenton"]),
    "MISSISSIPPI": dict(h=["Tuscaloosa Marine", "Selma Chalk"],
                        v=["Smackover", "Hosston"]),
}
DEFAULT_PLAY = dict(h=["Shale A", "Shale B", "Tight Sand"],
                    v=["Sandstone", "Carbonate", "Limestone"])
_ST_ABBR = {"TX": "TEXAS", "NM": "NEW MEXICO", "ND": "NORTH DAKOTA",
            "OK": "OKLAHOMA", "CO": "COLORADO", "WY": "WYOMING",
            "PA": "PENNSYLVANIA", "WV": "WEST VIRGINIA", "LA": "LOUISIANA",
            "KS": "KANSAS", "MI": "MICHIGAN", "MS": "MISSISSIPPI", "NE": "NEBRASKA"}


def _play_for(state):
    s = (str(state) or "").strip().upper()
    s = _ST_ABBR.get(s, s)
    return PLAYS.get(s, DEFAULT_PLAY)
OPERATORS  = ["Pioneer Natural Resources", "Diamondback Energy", "Occidental",
              "ConocoPhillips", "EOG Resources", "Apache Corp", "Devon Energy",
              "Coterra Energy", "Endeavor Energy", "Ovintiv"]
PUMPERS    = ["Halliburton", "SLB", "Liberty Energy", "ProPetro", "NexTier",
              "Calfrac", "ProFrac"]
PROP_TYPES_H = ["100 Mesh White Sand", "40/70 White Sand", "30/50 White Sand",
                "40/70 Brown Sand"]
PROP_TYPES_V = ["20/40 Ceramic", "16/30 Resin-Coated", "20/40 White Sand"]
FLUID_SYS_H  = ["Slickwater", "Slickwater", "Slickwater", "Hybrid"]
FLUID_SYS_V  = ["Crosslinked Gel", "Linear Gel", "Hybrid"]
DESIGN_H     = ["Plug & Perf", "Plug & Perf", "Plug & Perf", "Sliding Sleeve"]
DESIGN_V     = ["Cemented Liner Perf", "Conventional Perf", "Open Hole"]
STATUS_W     = ["Producing", "Producing", "Producing", "Completed", "Shut-in"]


# ── DDL (improved model) ─────────────────────────────────────────────────────
DDL = f"""
IF OBJECT_ID('{SCHEMA}.dv_well_stimulation','U') IS NOT NULL DROP TABLE {SCHEMA}.dv_well_stimulation;
IF OBJECT_ID('{SCHEMA}.dv_well_completion','U')  IS NOT NULL DROP TABLE {SCHEMA}.dv_well_completion;

CREATE TABLE {SCHEMA}.dv_well_completion(
    uwi                        nvarchar(40)  NOT NULL,
    completion_id              nvarchar(40)  NOT NULL,
    completion_type            nvarchar(60)  NOT NULL,
    completion_design          nvarchar(60)  NULL,
    well_orientation           nvarchar(20)  NULL,
    completion_date            date          NOT NULL,
    strat_unit_name            nvarchar(60)  NULL,
    top_depth                  float         NULL,
    base_depth                 float         NULL,
    measured_td_ft             float         NULL,
    lateral_length_ft          float         NULL,
    depth_ouom                 nvarchar(20)  NOT NULL,
    depth_datum                nvarchar(20)  NOT NULL,
    completion_status          nvarchar(40)  NOT NULL,
    primary_fluid              nvarchar(20)  NOT NULL,
    stage_count                int           NULL,
    total_clusters             int           NULL,
    avg_cluster_spacing_ft     float         NULL,
    frac_fluid_system          nvarchar(40)  NULL,
    proppant_type              nvarchar(60)  NULL,
    total_fluid_bbl            float         NULL,
    total_proppant_lbs         float         NULL,
    fluid_intensity_bbl_ft     float         NULL,
    proppant_intensity_lbs_ft  float         NULL,
    tubing_size_in             float         NULL,
    tubing_depth               float         NULL,
    artificial_lift_type       nvarchar(40)  NULL,
    operator_ba_id             nvarchar(120) NULL,
    contractor_ba_id           nvarchar(120) NULL,
    active_ind                 nvarchar(1)   NOT NULL,
    remark                     nvarchar(2000) NULL,
    source                     nvarchar(40)  NOT NULL,
    row_created_by             nvarchar(40)  NOT NULL,
    row_created_date           datetime2(7)  NOT NULL,
    CONSTRAINT pk_dv_well_completion PRIMARY KEY CLUSTERED (uwi ASC, completion_id ASC)
);

CREATE TABLE {SCHEMA}.dv_well_stimulation(
    uwi                        nvarchar(40)  NOT NULL,
    completion_id              nvarchar(40)  NOT NULL,
    stim_id                    nvarchar(40)  NOT NULL,
    stage_num                  int           NOT NULL,
    stim_type                  nvarchar(40)  NULL,
    stage_date                 date          NULL,
    stage_top_depth            float         NULL,
    stage_base_depth           float         NULL,
    num_clusters               int           NULL,
    cluster_spacing_ft         float         NULL,
    fluid_system               nvarchar(40)  NULL,
    fluid_volume_bbl           float         NULL,
    proppant_type              nvarchar(60)  NULL,
    proppant_mesh              nvarchar(40)  NULL,
    proppant_mass_lbs          float         NULL,
    max_proppant_conc_ppg      float         NULL,
    breakdown_pressure_psi     float         NULL,
    isip_psi                   float         NULL,
    avg_treating_pressure_psi  float         NULL,
    max_treating_pressure_psi  float         NULL,
    avg_rate_bpm               float         NULL,
    max_rate_bpm               float         NULL,
    screen_out_ind             nvarchar(1)   NULL,
    active_ind                 nvarchar(1)   NOT NULL,
    source                     nvarchar(40)  NOT NULL,
    row_created_by             nvarchar(40)  NOT NULL,
    row_created_date           datetime2(7)  NOT NULL,
    CONSTRAINT pk_dv_well_stimulation PRIMARY KEY CLUSTERED (uwi ASC, completion_id ASC, stim_id ASC)
);
CREATE INDEX ix_dv_well_stim_uwi ON {SCHEMA}.dv_well_stimulation(uwi);
"""


# ── generation ───────────────────────────────────────────────────────────────
def _well_context(engine, uwis):
    """Pull whatever context dv_well has for these wells (orientation hints,
    formation region, operator, dates). Missing wells get defaults."""
    ctx = {u: {} for u in uwis}
    if engine is None:
        return ctx
    from sqlalchemy import bindparam, text
    sql = text(f"""SELECT uwi, well_type, well_status, final_td, operator_name,
                 province_state, county, completion_date, spud_date
          FROM {SCHEMA}.dv_well WHERE uwi IN :uwis""").bindparams(
        bindparam("uwis", expanding=True))
    try:
        df = pd.read_sql(sql, engine, params={"uwis": uwis})
        for _, r in df.iterrows():
            ctx[str(r["uwi"])] = r.to_dict()
    except Exception as e:
        print(f"[warn] could not read dv_well context: {e}")
    return ctx


def _sample(engine, n):
    """Pull a random sample of N drilled wells (with context) to give
    completions. Returns (uwis, ctx). Requires a DB connection."""
    from sqlalchemy import text
    sql = text(f"""SELECT TOP (:n) uwi, well_type, well_status, final_td,
                 operator_name, province_state, county, completion_date, spud_date
          FROM {SCHEMA}.dv_well
          WHERE final_td IS NOT NULL AND final_td > 0
          ORDER BY NEWID()""")
    df = pd.read_sql(sql, engine, params={"n": int(n)})
    uwis, ctx = [], {}
    for _, r in df.iterrows():
        u = str(r["uwi"])
        uwis.append(u)
        ctx[u] = r.to_dict()
    return uwis, ctx


def _gen_one(uwi, ctx, rng):
    """Generate (completion_row, [stage_rows]) for one well."""
    now = dt.datetime.now()
    play = _play_for(ctx.get("province_state"))
    op  = ctx.get("operator_name") or rng.choice(OPERATORS)
    pumper = rng.choice(PUMPERS)
    if str(ctx.get("well_type", "")).upper().startswith("GAS"):
        primary = "GAS"
    elif play.get("gas"):
        primary = rng.choice(["GAS", "GAS", "GAS", "OIL"])
    else:
        primary = rng.choice(["OIL", "OIL", "OIL", "GAS"])
    comp_date = ctx.get("completion_date")
    if isinstance(comp_date, (pd.Timestamp, dt.date, dt.datetime)) and pd.notna(comp_date):
        comp_date = pd.Timestamp(comp_date).date()
    else:
        comp_date = (dt.date(2019, 1, 1) +
                     dt.timedelta(days=int(rng.integers(0, 2200))))

    horizontal = rng.random() < HORIZONTAL_FRACTION
    cid = f"{uwi}_C1"

    if horizontal:
        lateral = float(rng.integers(4500, 11000))
        stage_spacing = float(rng.uniform(150, 250))
        n_stages = int(np.clip(round(lateral / stage_spacing), 12, 65))
        toe_md = float(ctx.get("final_td") or rng.integers(12000, 22000))
        if toe_md < lateral + 6000:                      # keep heel sane
            toe_md = lateral + float(rng.integers(7000, 11000))
        heel_md = toe_md - lateral
        fluid_int = float(rng.uniform(35, 60))           # bbl/ft
        prop_int  = float(rng.uniform(1200, 2800))       # lbs/ft
        formation = rng.choice(play["h"])
        fluid_sys = rng.choice(FLUID_SYS_H)
        prop_type = rng.choice(PROP_TYPES_H)
        design    = rng.choice(DESIGN_H)
        ctype     = "Cased Hole Multistage Frac"
        rate_lo, rate_hi = 65, 100
        isip_lo, isip_hi = 4000, 7000
        treat_lo, treat_hi = 5500, 8500
    else:
        lateral = None
        n_stages = int(rng.integers(1, 4))
        toe_md = float(ctx.get("final_td") or rng.integers(6000, 13000))
        heel_md = toe_md - float(rng.integers(150, 800))
        fluid_int = prop_int = None
        formation = rng.choice(play["v"])
        fluid_sys = rng.choice(FLUID_SYS_V)
        prop_type = rng.choice(PROP_TYPES_V)
        design    = rng.choice(DESIGN_V)
        ctype     = "Perforate & Frac"
        rate_lo, rate_hi = 15, 40
        isip_lo, isip_hi = 2500, 5500
        treat_lo, treat_hi = 4000, 7000

    span = max(toe_md - heel_md, 1.0)
    stage_len = span / n_stages
    mesh = prop_type.split()[0] if "/" in prop_type else "100"

    stages = []
    tot_fluid = tot_prop = tot_clusters = 0.0
    csp_list = []
    for s in range(1, n_stages + 1):
        s_top = heel_md + (s - 1) * stage_len
        s_base = s_top + stage_len
        clusters = int(rng.integers(4, 10)) if horizontal else int(rng.integers(1, 4))
        csp = round(float(rng.uniform(15, 45)), 1) if horizontal else round(float(rng.uniform(20, 60)), 1)
        if horizontal:
            fluid_bbl = (fluid_int * lateral / n_stages) * float(rng.uniform(0.85, 1.15))
            prop_lbs  = (prop_int * lateral / n_stages) * float(rng.uniform(0.85, 1.15))
        else:
            fluid_bbl = float(rng.uniform(200, 900))
            prop_lbs  = float(rng.uniform(30000, 160000))
        isip = float(rng.integers(isip_lo, isip_hi))
        breakdown = isip + float(rng.integers(500, 2000))
        avg_treat = float(rng.integers(treat_lo, treat_hi))
        max_treat = avg_treat + float(rng.integers(300, 1800))
        avg_rate = round(float(rng.uniform(rate_lo, rate_hi)), 1)
        max_rate = round(avg_rate + float(rng.uniform(2, 12)), 1)
        conc = round(float(rng.uniform(1.5, 3.5)), 2)
        screen_out = "Y" if rng.random() < 0.03 else "N"
        stages.append(dict(
            uwi=uwi, completion_id=cid, stim_id=f"{cid}_S{s:02d}", stage_num=s,
            stim_type="Hydraulic Fracture", stage_date=comp_date,
            stage_top_depth=round(s_top, 1), stage_base_depth=round(s_base, 1),
            num_clusters=clusters, cluster_spacing_ft=csp,
            fluid_system=fluid_sys, fluid_volume_bbl=round(fluid_bbl, 1),
            proppant_type=prop_type, proppant_mesh=mesh,
            proppant_mass_lbs=round(prop_lbs, 0), max_proppant_conc_ppg=conc,
            breakdown_pressure_psi=round(breakdown, 0), isip_psi=round(isip, 0),
            avg_treating_pressure_psi=round(avg_treat, 0),
            max_treating_pressure_psi=round(max_treat, 0),
            avg_rate_bpm=avg_rate, max_rate_bpm=max_rate,
            screen_out_ind=screen_out, active_ind="Y", source="SYNTHETIC",
            row_created_by="gen_synthetic_completions", row_created_date=now,
        ))
        tot_fluid += fluid_bbl
        tot_prop  += prop_lbs
        tot_clusters += clusters
        csp_list.append(csp)

    comp = dict(
        uwi=uwi, completion_id=cid, completion_type=ctype, completion_design=design,
        well_orientation="Horizontal" if horizontal else "Vertical",
        completion_date=comp_date, strat_unit_name=formation,
        top_depth=round(heel_md, 1), base_depth=round(toe_md, 1),
        measured_td_ft=round(toe_md, 1),
        lateral_length_ft=round(lateral, 1) if lateral else None,
        depth_ouom="ft", depth_datum="KB",
        completion_status=rng.choice(STATUS_W), primary_fluid=primary,
        stage_count=n_stages, total_clusters=int(tot_clusters),
        avg_cluster_spacing_ft=round(float(np.mean(csp_list)), 1),
        frac_fluid_system=fluid_sys, proppant_type=prop_type,
        total_fluid_bbl=round(tot_fluid, 0), total_proppant_lbs=round(tot_prop, 0),
        fluid_intensity_bbl_ft=round(tot_fluid / lateral, 1) if lateral else None,
        proppant_intensity_lbs_ft=round(tot_prop / lateral, 0) if lateral else None,
        tubing_size_in=round(float(rng.choice([2.375, 2.875, 3.5])), 3),
        tubing_depth=round(heel_md - float(rng.integers(50, 400)), 1),
        artificial_lift_type=rng.choice(["ESP", "Gas Lift", "Rod Pump", "Flowing"]),
        operator_ba_id=op, contractor_ba_id=pumper,
        active_ind="Y", remark=None, source="SYNTHETIC",
        row_created_by="gen_synthetic_completions", row_created_date=now,
    )
    return comp, stages


def generate(uwis, ctx, seed=SEED):
    rng = np.random.default_rng(seed)
    comps, stages = [], []
    for u in uwis:
        c, st = _gen_one(u, ctx.get(u, {}), rng)
        comps.append(c)
        stages.extend(st)
    return pd.DataFrame(comps), pd.DataFrame(stages)


# ── DB I/O ───────────────────────────────────────────────────────────────────
def _engine():
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    url = URL.create("mssql+pyodbc", host=SERVER, database=DATABASE,
                     query={"driver": "ODBC Driver 17 for SQL Server",
                            "trusted_connection": "yes"})
    return create_engine(url, fast_executemany=True)


def _drop_referencing_fks(cx):
    """Drop every FK that references — or sits on — the two tables we recreate,
    so the DROP TABLE can proceed. They are NOT recreated (synthetic data)."""
    rows = cx.exec_driver_sql("""
        SELECT s.name AS sch, t.name AS tbl, fk.name AS fk
        FROM sys.foreign_keys fk
        JOIN sys.tables  t ON fk.parent_object_id = t.object_id
        JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE fk.referenced_object_id IN
                (OBJECT_ID('dataview.dv_well_completion'),
                 OBJECT_ID('dataview.dv_well_stimulation'))
           OR fk.parent_object_id IN
                (OBJECT_ID('dataview.dv_well_completion'),
                 OBJECT_ID('dataview.dv_well_stimulation'))
    """).fetchall()
    for sch, tbl, fk in rows:
        print(f"  dropping FK [{fk}] on {sch}.{tbl}")
        cx.exec_driver_sql(f"ALTER TABLE [{sch}].[{tbl}] DROP CONSTRAINT [{fk}]")
    return rows


def recreate_and_load(comp_df, stage_df):
    eng = _engine()
    with eng.begin() as cx:
        dropped = _drop_referencing_fks(cx)
        if dropped:
            print(f"  ({len(dropped)} FK constraint(s) dropped; not recreated)")
        for stmt in [s for s in DDL.split(";\n") if s.strip()]:
            cx.exec_driver_sql(stmt)
    comp_df.to_sql("dv_well_completion", eng, schema=SCHEMA,
                   if_exists="append", index=False, chunksize=500)
    stage_df.to_sql("dv_well_stimulation", eng, schema=SCHEMA,
                    if_exists="append", index=False, chunksize=1000)
    eng.dispose()


# ── main ─────────────────────────────────────────────────────────────────────
def append_load(comp_df, stage_df):
    """Add/refresh only the target wells, preserving every other well's data.
    Deletes any existing rows for these UWIs first so re-runs are idempotent."""
    from sqlalchemy import bindparam, inspect, text
    eng = _engine()
    if not inspect(eng).has_table("dv_well_completion", schema=SCHEMA):
        raise RuntimeError("Tables don't exist yet — run once without --append "
                           "to create them.")
    uwis = comp_df["uwi"].tolist()
    with eng.begin() as cx:
        for tbl in ("dv_well_stimulation", "dv_well_completion"):
            cx.execute(text(f"DELETE FROM {SCHEMA}.{tbl} WHERE uwi IN :u")
                       .bindparams(bindparam("u", expanding=True)), {"u": uwis})
    comp_df.to_sql("dv_well_completion", eng, schema=SCHEMA,
                   if_exists="append", index=False, chunksize=500)
    stage_df.to_sql("dv_well_stimulation", eng, schema=SCHEMA,
                    if_exists="append", index=False, chunksize=1000)
    eng.dispose()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="generate and print, do not recreate/load")
    ap.add_argument("--sample", type=int, metavar="N",
                    help="generate completions for N random drilled wells "
                         "(play-aware by state); needs a DB connection")
    ap.add_argument("--uwi-file", help="text file of UWIs (one per line)")
    ap.add_argument("--append", action="store_true",
                    help="add/refresh only the target wells without dropping "
                         "the tables (preserves other wells' data)")
    args = ap.parse_args()

    random.seed(SEED)
    # Sampling requires reading dv_well, so open an engine even on dry-run.
    need_read = (not args.dry_run) or (args.sample is not None)
    eng = _engine() if need_read else None

    if args.sample is not None:
        uwis, ctx = _sample(eng, args.sample)
        if not uwis:
            print("No wells matched the sample filter (final_td > 0).")
            return
    else:
        uwis = DEFAULT_UWIS
        if args.uwi_file:
            with open(args.uwi_file) as fh:
                uwis = [ln.strip() for ln in fh if ln.strip()
                        and ln.strip().lower() != "uwi"]
        uwis = list(dict.fromkeys(uwis))   # dedupe, keep order
        ctx = _well_context(eng, uwis)

    if eng is not None:
        eng.dispose()

    comp_df, stage_df = generate(uwis, ctx)

    print(f"Wells: {len(comp_df)}   Stages: {len(stage_df)}")
    print("  Orientation:", comp_df["well_orientation"].value_counts().to_dict())
    print("\nCompletion headers"
          + (f" (first 15 of {len(comp_df)}):" if len(comp_df) > 15 else ":"))
    cols = ["uwi", "well_orientation", "strat_unit_name", "lateral_length_ft",
            "stage_count", "total_fluid_bbl", "total_proppant_lbs",
            "proppant_intensity_lbs_ft", "completion_status"]
    with pd.option_context("display.width", 160, "display.max_columns", None):
        print(comp_df[cols].head(15).to_string(index=False))
        print("\nSample stages (first well):")
        first = comp_df.iloc[0]["uwi"]
        print(stage_df[stage_df.uwi == first].head(6)[
            ["stage_num", "stage_top_depth", "stage_base_depth", "num_clusters",
             "fluid_volume_bbl", "proppant_mass_lbs", "isip_psi",
             "max_treating_pressure_psi", "max_rate_bpm"]].to_string(index=False))

    if args.dry_run:
        print("\n[dry-run] no DB writes.")
        return
    if args.append:
        append_load(comp_df, stage_df)
        print(f"\nAppended {len(comp_df)} completions + {len(stage_df)} stages "
              f"for the target wells (other wells preserved).")
    else:
        recreate_and_load(comp_df, stage_df)
        print(f"\nLoaded {len(comp_df)} completions + {len(stage_df)} stages into "
              f"{DATABASE}.{SCHEMA}.")


if __name__ == "__main__":
    main()
