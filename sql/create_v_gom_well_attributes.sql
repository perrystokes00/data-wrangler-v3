-- =============================================================================
-- create_v_gom_well_attributes.sql
--
-- Sister view #1 in the federation pattern.
--
-- The dataview_federation.v_well view exposes the canonical 19 columns that
-- every well source can speak. Source-specialized attributes that don't have
-- onshore counterparts (BOEM lease numbers, water depth, MD/TVD/RKB/KOP,
-- bottom-hole coordinates, etc.) live in per-source SISTER views, joined to
-- v_well by uwi when a consumer needs the extra richness.
--
-- This is the first sister: BOEM-native attributes for Gulf of Mexico wells.
-- It exposes a curated 26-column subset of dataview_gom.well — the columns
-- the page actually consumes via _build_gom_popup_html and
-- _build_gom_scout_ticket_html. When future page surfaces need a column we
-- haven't exposed yet, we'll ALTER VIEW to add it explicitly.
--
-- Naming convention: BOEM-native names (bottom_latitude, not bottom_lat;
-- true_vertical_depth_ft, not tvd_ft). The popup/ticket HTML builders are
-- being updated to read these source-native names in Session 2 — the view
-- reflects the source schema, the page adapts to the view.
--
-- Join semantics: keyed by uwi (CONVERT(VARCHAR(36), well_id) AS uwi).
-- This matches v_well's uwi shape for the GOM arm. Pattern for callers:
--
--     SELECT w.*, g.*
--     FROM dataview_federation.v_well w
--     LEFT JOIN dataview_federation.v_gom_well_attributes g
--       ON g.uwi = w.uwi
--     WHERE w.dv_schema = 'dataview_gom'
--
-- LEFT JOIN is the rule even when filtering to dv_schema='dataview_gom' —
-- belt and suspenders, and it makes the "All schemas" query work the same
-- way (onshore wells get NULL for every sister column, popup builders
-- already handle None gracefully).
--
-- Author: Session 2, 2026-05-25
-- =============================================================================

USE [DataView];
GO

-- Drop and recreate so re-runs are idempotent during development.
-- In production we'd ALTER VIEW, but we're solo-dev and the view is dormant.
IF OBJECT_ID('dataview_federation.v_gom_well_attributes', 'V') IS NOT NULL
    DROP VIEW dataview_federation.v_gom_well_attributes;
GO

CREATE VIEW dataview_federation.v_gom_well_attributes AS
SELECT
    -- =============================================================
    -- JOIN KEY — matches v_well.uwi for GOM rows
    -- =============================================================
    CONVERT(VARCHAR(36), w.well_id) AS uwi,

    -- =============================================================
    -- IDENTITY — BOEM-native names
    -- well_id kept as a separate column (NVARCHAR(40), not VARCHAR(36))
    -- because the popup HTML embeds it as data-well-id and the existing
    -- click-handler JS parses it as a string. Keeping a dedicated column
    -- prevents callers from having to remember they're the same value.
    -- =============================================================
    CAST(w.well_id AS NVARCHAR(40)) AS well_id,
    w.well_name_suffix,
    w.api_well_number,
    w.company_name,

    -- =============================================================
    -- LEASE / LOCATION (BOEM)
    -- =============================================================
    w.surface_lease_number,
    w.bottom_lease_number,
    w.bottom_area_code,
    w.bottom_block_number,
    w.region,

    -- =============================================================
    -- CLASSIFICATION CODES (raw BOEM codes — no canonicalization)
    -- =============================================================
    w.type_code,
    w.status_code,
    w.casing_cut_code,

    -- =============================================================
    -- DATES — string-formatted to match what FOR JSON PATH callers
    -- already pass to the page. Doing the conversion in the view
    -- means consumers don't repeat the CONVERT in every query.
    -- =============================================================
    CONVERT(VARCHAR(10), w.spud_date,        120) AS spud_date,
    CONVERT(VARCHAR(10), w.total_depth_date, 120) AS total_depth_date,
    CONVERT(VARCHAR(10), w.status_date,      120) AS status_date,

    -- =============================================================
    -- DEPTHS — all CAST to FLOAT so JSON serialization is clean
    -- (source columns are DECIMAL with various scales; FLOAT
    -- normalizes them for downstream Python consumption)
    -- =============================================================
    CAST(w.bh_total_md_ft         AS FLOAT) AS bh_total_md_ft,
    CAST(w.true_vertical_depth_ft AS FLOAT) AS true_vertical_depth_ft,
    CAST(w.tvd_subsea_ft          AS FLOAT) AS tvd_subsea_ft,
    CAST(w.rkb_ft                 AS FLOAT) AS rkb_ft,
    CAST(w.kop_ft                 AS FLOAT) AS kop_ft,
    CAST(w.water_depth_ft         AS FLOAT) AS water_depth_ft,

    -- =============================================================
    -- COORDINATES — surface and bottom-hole, both as FLOAT.
    -- Surface coords are ALSO in v_well as lat/lon. We re-expose them
    -- here under their source-native names so scout-ticket code that
    -- pulls from the sister doesn't have to know v_well exists.
    -- This is intentional duplication for self-contained reads.
    -- =============================================================
    CAST(w.surface_latitude   AS FLOAT) AS surface_latitude,
    CAST(w.surface_longitude  AS FLOAT) AS surface_longitude,
    CAST(w.bottom_latitude    AS FLOAT) AS bottom_latitude,
    CAST(w.bottom_longitude   AS FLOAT) AS bottom_longitude,

    -- =============================================================
    -- PROVENANCE
    -- =============================================================
    w.source_file
FROM dataview_gom.well w;
GO

-- Smoke test (uncomment to run in SSMS):
-- SELECT COUNT(*) AS sister_row_count FROM dataview_federation.v_gom_well_attributes;
-- SELECT TOP 5 * FROM dataview_federation.v_gom_well_attributes;
-- SELECT COUNT(*) AS unmatched
--   FROM dataview_federation.v_well w
--   LEFT JOIN dataview_federation.v_gom_well_attributes g ON g.uwi = w.uwi
--  WHERE w.dv_schema = 'dataview_gom' AND g.uwi IS NULL;
-- -- Expected: sister_row_count == 54,675, unmatched == 0
