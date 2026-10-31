"""
Temporal-Provenance Conflict Graph (TPCG) Module.
Re-exports the TPCG graph manager and related classes for easy top-level imports.
"""

from app.graph.tpcg import (
    TemporalProvenanceConflictGraph,
    get_original_filename,
    extract_text_from_file,
    parse_date_for_comparison,
    parse_version_tuple,
    to_json_safe,
)

__all__ = [
    "TemporalProvenanceConflictGraph",
    "get_original_filename",
    "extract_text_from_file",
    "parse_date_for_comparison",
    "parse_version_tuple",
    "to_json_safe",
]
