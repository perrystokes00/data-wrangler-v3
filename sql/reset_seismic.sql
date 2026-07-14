-- Clear existing seismic rows so promote rebuilds them deduped (Model A).
-- dv_seis_set had one-row-per-file duplicates; the normalized promote collapses
-- them to one survey per name. dv_seis_line (child) gets one row per file.
-- Run, then re-run Promote.
SET QUOTED_IDENTIFIER ON;
DELETE FROM dataview.dv_seis_line;
GO
DELETE FROM dataview.dv_seis_set;
GO
PRINT 'seismic cleared — re-run Promote to rebuild deduped survey + lines';
GO
