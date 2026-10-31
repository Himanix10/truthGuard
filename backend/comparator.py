"""
Comparator Module.
Re-exports compare_two_documents and CompareRequest for clean top-level imports.
"""

from app.graph.comparator import (
    compare_two_documents,
    CompareRequest,
    extract_informative_passages,
)

__all__ = [
    "compare_two_documents",
    "CompareRequest",
    "extract_informative_passages",
]

