-- dv_catalog_governance.sql
-- Creates governance tables for DataView v3 File Catalog
-- Run in SSMS against DataView and DataView_Test

USE DataView;
GO

IF OBJECT_ID('dataview.dv_catalog_user','U') IS NULL
CREATE TABLE dataview.dv_catalog_user (
    user_id          NVARCHAR(40)   NOT NULL,
    username         NVARCHAR(80)   NOT NULL,
    full_name        NVARCHAR(255)  NOT NULL,
    email            NVARCHAR(255)  NULL,
    password_hash    NVARCHAR(64)   NOT NULL,  -- SHA256 hex
    role             NVARCHAR(20)   NOT NULL DEFAULT 'CATALOGER',
    active_ind       NVARCHAR(1)    NOT NULL DEFAULT 'Y',
    last_login       DATETIME2      NULL,
    row_created_by   NVARCHAR(40)   NOT NULL DEFAULT 'SYSTEM',
    row_created_date DATETIME2      NOT NULL DEFAULT GETDATE(),
    CONSTRAINT pk_dv_catalog_user    PRIMARY KEY (user_id),
    CONSTRAINT uq_dv_catalog_user_un UNIQUE (username),
    CONSTRAINT ck_dv_catalog_user_r  CHECK (role IN ('MANAGER','DELEGATE','CATALOGER')),
    CONSTRAINT ck_dv_catalog_user_ai CHECK (active_ind IN ('Y','N'))
);
GO

IF OBJECT_ID('dataview.dv_catalog_group','U') IS NULL
CREATE TABLE dataview.dv_catalog_group (
    group_id         NVARCHAR(40)   NOT NULL,
    group_name       NVARCHAR(255)  NOT NULL,
    description      NVARCHAR(1000) NULL,
    doc_type_filter  NVARCHAR(500)  NULL,  -- comma-separated doc types
    root_path_filter NVARCHAR(1000) NULL,  -- path prefix filter
    status_filter    NVARCHAR(40)   NULL DEFAULT 'UNCATALOGED',
    created_by       NVARCHAR(40)   NOT NULL,
    row_created_date DATETIME2      NOT NULL DEFAULT GETDATE(),
    active_ind       NVARCHAR(1)    NOT NULL DEFAULT 'Y',
    CONSTRAINT pk_dv_catalog_group  PRIMARY KEY (group_id),
    CONSTRAINT ck_dv_catalog_grp_ai CHECK (active_ind IN ('Y','N'))
);
GO

IF OBJECT_ID('dataview.dv_catalog_assignment','U') IS NULL
CREATE TABLE dataview.dv_catalog_assignment (
    assignment_id    NVARCHAR(40)   NOT NULL,
    group_id         NVARCHAR(40)   NOT NULL,
    user_id          NVARCHAR(40)   NOT NULL,
    assigned_by      NVARCHAR(40)   NOT NULL,
    assigned_date    DATETIME2      NOT NULL DEFAULT GETDATE(),
    completed_date   DATETIME2      NULL,
    status           NVARCHAR(20)   NOT NULL DEFAULT 'ACTIVE',
    notes            NVARCHAR(1000) NULL,
    CONSTRAINT pk_dv_catalog_asgn  PRIMARY KEY (assignment_id),
    CONSTRAINT fk_dv_asgn_group    FOREIGN KEY (group_id)
        REFERENCES dataview.dv_catalog_group(group_id),
    CONSTRAINT fk_dv_asgn_user     FOREIGN KEY (user_id)
        REFERENCES dataview.dv_catalog_user(user_id)
);
GO

IF OBJECT_ID('dataview.dv_catalog_file_assignment','U') IS NULL
CREATE TABLE dataview.dv_catalog_file_assignment (
    file_assignment_id NVARCHAR(40)  NOT NULL,
    assignment_id      NVARCHAR(40)  NOT NULL,
    inventory_id       NVARCHAR(40)  NOT NULL,
    status             NVARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    completed_date     DATETIME2     NULL,
    completed_by       NVARCHAR(40)  NULL,
    notes              NVARCHAR(1000) NULL,
    CONSTRAINT pk_dv_catalog_fa    PRIMARY KEY (file_assignment_id),
    CONSTRAINT fk_dv_fa_asgn       FOREIGN KEY (assignment_id)
        REFERENCES dataview.dv_catalog_assignment(assignment_id),
    CONSTRAINT fk_dv_fa_inv        FOREIGN KEY (inventory_id)
        REFERENCES dataview.dv_global_file_catalog(inventory_id)
);
GO

-- Verify
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'dataview'
  AND table_name LIKE 'dv_catalog%'
ORDER BY table_name;
GO
