-- Clear all catalog tables (child tables first)
DELETE FROM las_catalog.DLIS_CHANNEL;
DELETE FROM las_catalog.DLIS_PARAMETER;
DELETE FROM las_catalog.DLIS_FRAME;
DELETE FROM las_catalog.DLIS_LOGICAL_FILE;
DELETE FROM las_catalog.DLIS_FILE;

DELETE FROM las_catalog.LIS_CHANNEL;
DELETE FROM las_catalog.LIS_FILE;

DELETE FROM las_catalog.LAS_FILE_CURVE;
DELETE FROM las_catalog.LAS_FILE_PARAMETER;
DELETE FROM las_catalog.LAS_FILE;

DELETE FROM las_catalog.WL_FILE_UWI_MAP;

-- WL_REPOSITORY last (all file tables reference it)
DELETE FROM las_catalog.WL_REPOSITORY;
