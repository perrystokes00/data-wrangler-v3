# 🛢️ Data Wrangler

**AI-Assisted Petroleum Data Management — PPDM 3.9 ETL Pipeline**

[![Demo Video](https://img.shields.io/badge/▶_Watch_Demo-YouTube-red?style=for-the-badge&logo=youtube)](https://www.youtube.com/watch?v=o8tCEyVYQJ8)
[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.30+-FF4B4B?style=for-the-badge&logo=streamlit)](https://streamlit.io)
[![SQL Server](https://img.shields.io/badge/SQL_Server-2019+-CC2927?style=for-the-badge&logo=microsoftsqlserver)](https://microsoft.com/sql-server)

---

## Demo

<!-- Replace o8tCEyVYQJ8 with your YouTube video ID after uploading -->
[![Data Wrangler Demo](https://img.youtube.com/vi/o8tCEyVYQJ8/maxresdefault.jpg)](https://www.youtube.com/watch?v=o8tCEyVYQJ8)

*Click the image above to watch the full demo (~10 minutes)*

---

## What It Does

Data Wrangler loads petroleum data into a fully normalized **PPDM 3.9** SQL Server database. It handles schema mapping, foreign key resolution, and batch loading — all from a browser interface powered by Streamlit and Anthropic Claude.

- **Map once, load forever** — save a fingerprint from the first interactive run; all subsequent files with the same column structure load automatically
- **FK auto-seeding** — parent tables (`field`, `business_associate`, `r_well_status`) are populated automatically from source data before each load
- **Unattended batch loading** — drop files into a watch folder and walk away
- **400,000 wells loaded in under 2 minutes** on a standard laptop

---

## Features

| Tool | Description |
|------|-------------|
| 🤖 **AI Assistant** | Claude-powered chat for database loading questions |
| 📋 **Reference Table Manager** | Seed PPDM reference and entity tables from source data |
| 📏 **Rules Manager** | Normalization and validation rules |
| 🔗 **ERD Diagrams** | Interactive PPDM 3.9 entity-relationship diagrams |
| 🗄️ **Database Explorer** | Query, browse, and export database tables |
| 📦 **Batch Loader** | Queue-based unattended loading with file watcher |

### Pipeline Stages

```
Ingest → Stage → Normalize → Map → FK Seed → FK Check → Validate → Promote
```

1. **Ingest** — auto-detects delimiter, sanitizes headers, deduplicates columns
2. **Stage** — loads source data into a staging schema
3. **Normalize** — server-side transforms (UPPER, TRIM, SHA1, TRY_CONVERT)
4. **Map** — match source columns to PPDM target columns with transforms
5. **FK Seed** — auto-populates parent tables from staging data
6. **FK Check** — validates referential integrity before promoting
7. **Validate** — NOT NULL and duplicate PK checks
8. **Promote** — server-side INSERT SELECT into PPDM tables

---

## Requirements

- Python 3.11+
- SQL Server 2019+ (Express or higher)
- ODBC Driver 17 for SQL Server
- Anthropic API key (for AI features)

---

## Installation

```bash
# Clone the repository
git clone https://github.com/perrystokes00/Data-Wrangler-New.git
cd Data-Wrangler-New

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
```

---

## Configuration

Create a `.streamlit/secrets.toml` file:

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
```

On first launch, connect to your SQL Server instance from the sidebar and select the PPDM 3.9 schema.

---

## Batch Loading

Run the queue once:
```bash
python bulk_runner.py --db-server SERVER\INSTANCE --db-name PPDM39 --windows-auth
```

Run as a continuous file watcher:
```bash
python bulk_runner.py --db-server SERVER\INSTANCE --db-name PPDM39 --windows-auth --watch
```

Or use the included `run_batch.bat` / `run_watcher.bat` for double-click execution on Windows.

---

## Architecture

```
page_pipeline.py    ← Interactive ETL pipeline (8 stages)
page_bulk.py        ← Batch loader (queue, scheduler, file watcher)
bulk_runner.py      ← Headless batch runner (CLI / Task Scheduler)
app.py              ← Main Streamlit app + sidebar
modules/
  db.py             ← SQL Server connection
  staging.py        ← File ingest and staging
  mapping.py        ← Column mapping and fingerprints
  promote.py        ← Server-side INSERT SELECT
  fk.py             ← FK constraint checking
  schema.py         ← PPDM schema registry
  ppdm_agent.py     ← Claude AI assistant
```

---

## PPDM 3.9

Data Wrangler implements the [Professional Petroleum Data Management (PPDM) 3.9](https://ppdm.org) standard — the industry standard data model for oil and gas data management. The schema registry includes 2,600+ tables and 18,000+ FK constraints.

---

## Author

**Perry Stokes** · 2026
*Wrangling data since forever*
