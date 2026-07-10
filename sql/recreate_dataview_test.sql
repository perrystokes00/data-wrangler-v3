/* ============================================================================
   recreate_dataview_test.sql
   ----------------------------------------------------------------------------
   Drops the DataView_Test database entirely and creates a fresh, EMPTY one
   (no schemas, no tables — you rebuild structure with your DDL afterward).

   DESTRUCTIVE & IRREVERSIBLE: this deletes the database and everything in it.
   Make sure you have a backup if there's anything you need.

   Must be run from a connection to `master` (you can't drop the DB you're in):
     sqlcmd -S localhost\SQLEXPRESS -d master -E -i recreate_dataview_test.sql
   (or open in SSMS, make sure the connection is on master, and Execute)
   ============================================================================ */
USE master;
GO

/* Drop if it exists. SINGLE_USER WITH ROLLBACK IMMEDIATE forcibly disconnects
   any other sessions (including an open app/SSMS tab) so the drop can proceed. */
IF DB_ID(N'DataView_Test') IS NOT NULL
BEGIN
    ALTER DATABASE DataView_Test SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE DataView_Test;
END
GO

/* Create a fresh empty database (server-default collation, paths, and sizing). */
CREATE DATABASE DataView_Test;
GO

PRINT 'DataView_Test dropped and recreated empty.';
GO
