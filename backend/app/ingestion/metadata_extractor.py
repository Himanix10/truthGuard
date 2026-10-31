import re
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    document_title: Optional[str] = Field(
        default=None, description="Document title extracted from header or explicit title label"
    )
    effective_date: Optional[str] = Field(
        default=None, description="Date when policy/document becomes effective"
    )
    publication_or_issue_date: Optional[str] = Field(
        default=None, description="Publication, issue, release, or creation date"
    )
    version_number: Optional[str] = Field(
        default=None, description="Version or revision number"
    )
    policy_or_document_identifier: Optional[str] = Field(
        default=None, description="Unique policy, document, or standard reference code"
    )
    geographic_or_organizational_scope: Optional[str] = Field(
        default=None, description="Scope such as global, regional, country, or department"
    )
    appears_amendment_or_replacement: bool = Field(
        default=False,
        description="Whether the document appears to amend, supersede, or replace an earlier policy",
    )
    referenced_parent_or_previous_policy_identifier: Optional[str] = Field(
        default=None,
        description="Identifier of parent, prior, or superseded document referenced",
    )


def is_plausible_date(value: str) -> bool:
    """Checks if a string plausibly contains a date."""
    if not value or len(value) < 4 or len(value) > 50:
        return False
    has_digit = bool(re.search(r"\d", value))
    has_month = bool(
        re.search(
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b",
            value,
            re.IGNORECASE,
        )
    )
    return has_digit or has_month


def clean_matched_value(value: str) -> str:
    """Strips outer whitespace and trailing punctuation."""
    return re.sub(r"[\.,;:_|]+$", "", value.strip()).strip()


def extract_title(text: str) -> Optional[str]:
    """
    Extracts the document title using explicit labels, markdown headers,
    or the first substantive prominent line.
    """
    if not text:
        return None

    # 1. Explicit Title label
    explicit_match = re.search(
        r"(?:^|\n)\s*(?:Document\s+Title|Policy\s+Title|Title)\s*[:\-–]\s*([^\n\r]+)",
        text,
        re.IGNORECASE,
    )
    if explicit_match:
        cand = clean_matched_value(explicit_match.group(1))
        cand = re.sub(r"^[#*\s]+|[#*\s]+$", "", cand).strip()
        if cand:
            return cand

    # 2. Markdown H1 header (# Title)
    md_match = re.search(r"(?:^|\n)\s*#\s+([^\n\r]+)", text)
    if md_match:
        cand = clean_matched_value(md_match.group(1))
        if cand:
            return cand

    # 3. Rule-based inspection of initial lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    skip_patterns = [
        r"^page\s+\d+",
        r"^\d+$",
        r"^confidential\b",
        r"^draft\b",
        r"^internal\s*\|\s*not for clients",
        r"^table of contents",
        r"^[=\-_*#]{3,}$",
        r"^(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
        r"^\d{4}-\d{2}-\d{2}",
    ]

    for line in lines[:10]:
        line_clean = re.sub(r"^[#*\s]+|[#*\s]+$", "", line).strip()
        if len(line_clean) < 3 or len(line_clean) > 120:
            continue
        if any(re.search(pat, line_clean, re.IGNORECASE) for pat in skip_patterns):
            continue
        # Avoid bullet points or numbered sections
        if re.match(r"^\d+\.\s+", line_clean):
            continue
        return line_clean

    return None


def extract_effective_date(text: str) -> Optional[str]:
    """Extracts the effective date when explicitly defined."""
    if not text:
        return None

    patterns = [
        r"(?:effective\s+date|effective\s+as\s+of|effective\s+from|takes\s+effect\s+on|in\s+effect\s+since|date\s+of\s+enforcement)\s*[:\-–]?\s*([A-Za-z0-9, \/\-\.]+?)(?=\s*(?:\n|\r|\.|\;|\(|\)|\||$))",
        r"(?:^|\n)\s*effective\s*[:\-–]\s*([A-Za-z0-9, \/\-\.]+?)(?=\s*(?:\n|\r|\.|\;|\(|\)|\||$))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            cand = clean_matched_value(match.group(1))
            if is_plausible_date(cand):
                return cand

    return None


def extract_publication_or_issue_date(text: str) -> Optional[str]:
    """Extracts publication, issue, release, or created date."""
    if not text:
        return None

    patterns = [
        r"(?:publication\s+date|published\s+date|published\s+on|issue\s+date|issued\s+on|date\s+of\s+issue|release\s+date|released\s+on|created\s+date)\s*[:\-–]?\s*([A-Za-z0-9, \/\-\.]+?)(?=\s*(?:\n|\r|\.|\;|\(|\)|\||$))",
        r"(?:^|\n)\s*(?:date|issued|published)\s*[:\-–]\s*([A-Za-z0-9, \/\-\.]+?)(?=\s*(?:\n|\r|\.|\;|\(|\)|\||$))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            cand = clean_matched_value(match.group(1))
            if is_plausible_date(cand):
                return cand

    # Header date match in top section
    header_text = text[:800]
    date_patterns = [
        r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",
        r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",
    ]
    for date_pat in date_patterns:
        m = re.search(date_pat, header_text, re.IGNORECASE)
        if m:
            return m.group(0).strip()

    return None


def extract_version_number(text: str) -> Optional[str]:
    """Extracts the version or revision number."""
    if not text:
        return None

    patterns = [
        r"(?:version|ver\.|v\.|revision|rev\.)\s*[:#\-–]?\s*([vV]?\d+(?:\.\d+)*(?:-[a-zA-Z0-9]+)?)",
        r"(?:^|\n|\s)\b[vV](\d+\.\d+(?:\.\d+)?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            cand = match.group(1).strip()
            if re.search(r"\d", cand):
                return cand

    return None


def extract_policy_or_document_identifier(text: str) -> Optional[str]:
    """Extracts unique document, policy, or standard identifier code."""
    if not text:
        return None

    patterns = [
        r"(?:policy\s+identifier|policy\s+id|policy\s+number|policy\s+code|policy\s+ref|policy\s+no\.?)\s*[:#\-–]\s*([A-Za-z0-9\-_./]+)",
        r"(?:document\s+identifier|document\s+id|document\s+number|document\s+code|document\s+ref|document\s+no\.?|doc\s+id)\s*[:#\-–]\s*([A-Za-z0-9\-_./]+)",
        r"(?:reference\s+number|ref\s+no\.?|standard\s+number|sop\s+no\.?)\s*[:#\-–]\s*([A-Za-z0-9\-_./]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            cand = clean_matched_value(match.group(1))
            if cand:
                return cand

    # Prominent reference codes like POL-2024-001 or DOC-HR-101 in header
    header_text = text[:1500]
    id_pattern = r"\b([A-Z]{2,6}-[A-Z0-9]{2,8}-\d{2,8}(?:[A-Za-z0-9\-_.]*))\b"
    m = re.search(id_pattern, header_text)
    if m:
        return m.group(1).strip()

    return None


def extract_geographic_or_organizational_scope(text: str) -> Optional[str]:
    """Extracts geographic or organizational scope (Global, Regional, Country, Department)."""
    if not text:
        return None

    # 1. Explicit scope or department labels
    patterns = [
        r"(?:geographic\s+scope|organizational\s+scope|scope|jurisdiction|applicability|applies\s+to|target\s+audience)\s*[:\-–]\s*([^\n\r;]+)",
        r"(?:department|division)\s*[:\-–]\s*([^\n\r;]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            cand = clean_matched_value(match.group(1))
            if cand and len(cand) <= 100:
                return cand

    # 2. Check for corporate scope badges in header lines
    header_lines = text[:1000].splitlines()
    for line in header_lines:
        line_clean = line.strip()
        if re.search(r"\binternal\b", line_clean, re.IGNORECASE) and (
            "not for clients" in line_clean.lower() or "|" in line_clean
        ):
            return line_clean

    # 3. Keyword detection in header
    header_section = text[:1500]
    if re.search(r"\b(global|worldwide|enterprise-wide|company-wide)\b", header_section, re.IGNORECASE):
        return "Global"
    reg_match = re.search(r"\b(regional|emea|apac|latam|north america)\b", header_section, re.IGNORECASE)
    if reg_match:
        return f"Regional ({reg_match.group(1).upper()})"
    if re.search(r"\binternal\s+only\b|\binternal\s+use\b", header_section, re.IGNORECASE):
        return "Internal"

    return None


def extract_appears_amendment_or_replacement(text: str) -> bool:
    """Checks whether the document contains indicators of amendment, supersession, or replacement."""
    if not text:
        return False

    amendment_keywords = [
        r"\bamendment\b",
        r"\bamends\b",
        r"\bamended\b",
        r"\bsupersedes\b",
        r"\bsuperseded\b",
        r"\breplaces\b",
        r"\breplacement\s+of\b",
        r"\breplacement\b",
        r"\baddendum\b",
        r"\bsubstitutes\b",
        r"\boverrides\b",
        r"\brevises\s+policy\b",
        r"\breplaces\s+version\b",
    ]
    for kw in amendment_keywords:
        if re.search(kw, text, re.IGNORECASE):
            return True
    return False


def extract_referenced_parent_or_previous_policy_identifier(text: str) -> Optional[str]:
    """Extracts referenced parent, previous, or superseded policy identifier."""
    if not text:
        return None

    patterns = [
        r"(?:supersedes|replaces|amends|amendment\s+to|substitutes|overrides|revision\s+to)\s*(?:policy|document|standard|doc|id|code|no\.?)?\s*[:\-–]?\s*([A-Za-z0-9\-_./]+(?:-[A-Za-z0-9\-_./]+)*)",
        r"(?:previous\s+policy|prior\s+policy|parent\s+policy|preceding\s+policy|referenced\s+policy)\s*(?:identifier|id|number|code|no\.?)?\s*[:\-–]?\s*([A-Za-z0-9\-_./]+)",
        r"(?:replaces\s+version|previous\s+version)\s*[:\-–]?\s*([vV]?\d+(?:\.\d+)*(?:-[a-zA-Z0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            cand = clean_matched_value(match.group(1))
            if cand.lower() not in {"the", "a", "an", "all", "this", "our", "existing", "it"} and len(cand) > 1:
                return cand

    return None


def extract_document_metadata(text: str, fallback_filename: Optional[str] = None) -> DocumentMetadata:
    """
    Extracts all metadata fields from document text using rule-based and regex heuristics.
    Returns null for any field that cannot be identified.
    """
    if not text or not text.strip():
        return DocumentMetadata()

    return DocumentMetadata(
        document_title=extract_title(text),
        effective_date=extract_effective_date(text),
        publication_or_issue_date=extract_publication_or_issue_date(text),
        version_number=extract_version_number(text),
        policy_or_document_identifier=extract_policy_or_document_identifier(text),
        geographic_or_organizational_scope=extract_geographic_or_organizational_scope(text),
        appears_amendment_or_replacement=extract_appears_amendment_or_replacement(text),
        referenced_parent_or_previous_policy_identifier=extract_referenced_parent_or_previous_policy_identifier(text),
    )
