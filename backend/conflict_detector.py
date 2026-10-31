"""
Conflict Detection Module.
Re-exports ConflictDetector and helper utilities for easy top-level imports.
"""

from app.graph.conflict_detector import (
    ConflictDetector,
    extract_evidence_snippet,
    RULE_TOPIC_PATTERNS,
)

__all__ = [
    "ConflictDetector",
    "extract_evidence_snippet",
    "RULE_TOPIC_PATTERNS",
]

