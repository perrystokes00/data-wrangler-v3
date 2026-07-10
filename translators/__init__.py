"""
DataView v3 — Universal Well Data Importer
==========================================
Layer 1: format_detective  — detects file type, encoding, structure
Layer 2: column_mapper     — ML + Claude column → dv_well field mapping
Layer 3: (coming) well_loader — writes confirmed mappings to DB
Layer 4: (coming) page_importer.py — Streamlit UI
"""
from importer.format_detective import detect, DetectionResult
from importer.column_mapper import ColumnMapper, MappingResult, ColumnMapping

__all__ = [
    "detect",
    "DetectionResult",
    "ColumnMapper",
    "MappingResult",
    "ColumnMapping",
]
