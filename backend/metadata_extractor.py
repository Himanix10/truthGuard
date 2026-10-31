"""
Document Metadata Extractor Module.
Provides rule-based and regex extraction of document attributes.
"""

from app.ingestion.metadata_extractor import (
    DocumentMetadata,
    extract_document_metadata,
    extract_title,
    extract_effective_date,
    extract_publication_or_issue_date,
    extract_version_number,
    extract_policy_or_document_identifier,
    extract_geographic_or_organizational_scope,
    extract_appears_amendment_or_replacement,
    extract_referenced_parent_or_previous_policy_identifier,
)

__all__ = [
    "DocumentMetadata",
    "extract_document_metadata",
    "extract_title",
    "extract_effective_date",
    "extract_publication_or_issue_date",
    "extract_version_number",
    "extract_policy_or_document_identifier",
    "extract_geographic_or_organizational_scope",
    "extract_appears_amendment_or_replacement",
    "extract_referenced_parent_or_previous_policy_identifier",
]
