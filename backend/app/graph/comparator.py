"""
Document Comparison Module for TruthGuard-Chronos.

Compares two policy documents side-by-side using:
  1. Extracted document metadata (title, version, issue date, effective date, scope, identifier)
  2. Temporal-Provenance Conflict Graph (TPCG) relationships (SUPERSEDES, AMENDS, SAME_POLICY, RELATED_TO)
  3. Conflict detection and classification (supersession, scope_conflict, temporal_conflict, insufficient_evidence)
  4. Text passage extraction and rule difference analysis
  5. Audit-ready citations and deterministic outcome arbitration (RESOLVED, CONFLICT, ABSTAIN)

Explicit precedence rules:
  - Do NOT invent relationships, differences, or conflict resolutions.
  - If explicit precedence cannot be established, surface the differences rather than guessing.
  - An outcome is only RESOLVED if explicit supersession/amendment evidence exists or if no conflict exists.
  - If documents conflict without explicit precedence, the outcome is CONFLICT.
  - If text is missing/empty or metadata is insufficient, the outcome is ABSTAIN.
"""

import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field

try:
    from app.graph.tpcg import (
        TemporalProvenanceConflictGraph,
        get_original_filename,
        extract_text_from_file,
        parse_date_for_comparison,
        parse_version_tuple,
    )
    from app.ingestion.metadata_extractor import extract_document_metadata, DocumentMetadata
    from app.graph.conflict_detector import ConflictDetector, extract_evidence_snippet, RULE_TOPIC_PATTERNS
except ImportError:
    from tpcg import (
        TemporalProvenanceConflictGraph,
        get_original_filename,
        extract_text_from_file,
        parse_date_for_comparison,
        parse_version_tuple,
    )
    from metadata_extractor import extract_document_metadata, DocumentMetadata
    from conflict_detector import ConflictDetector, extract_evidence_snippet, RULE_TOPIC_PATTERNS


class CompareRequest(BaseModel):
    file_a: Optional[str] = Field(
        default=None,
        description="Filename or unique saved filename of the first document.",
    )
    file_b: Optional[str] = Field(
        default=None,
        description="Filename or unique saved filename of the second document.",
    )
    doc1: Optional[str] = Field(
        default=None,
        description="Alternative alias for file_a.",
    )
    doc2: Optional[str] = Field(
        default=None,
        description="Alternative alias for file_b.",
    )
    doc_a: Optional[str] = Field(
        default=None,
        description="Alternative alias for file_a.",
    )
    doc_b: Optional[str] = Field(
        default=None,
        description="Alternative alias for file_b.",
    )
    filename_a: Optional[str] = Field(
        default=None,
        description="Alternative alias for file_a.",
    )
    filename_b: Optional[str] = Field(
        default=None,
        description="Alternative alias for file_b.",
    )
    document1: Optional[str] = Field(
        default=None,
        description="Alternative alias for file_a.",
    )
    document2: Optional[str] = Field(
        default=None,
        description="Alternative alias for file_b.",
    )


def extract_informative_passages(text: str, max_passages: int = 4) -> List[str]:
    """
    Extracts representative non-empty paragraphs or sections from document text.
    Filters out single-word lines or boilerplate whitespace.
    """
    if not text or not text.strip():
        return []

    # Split on double newlines or large paragraph breaks
    raw_paras = re.split(r"\n\s*\n+", text.strip())
    clean_paras = []
    seen = set()

    for p in raw_paras:
        cleaned = re.sub(r"\s+", " ", p).strip()
        # Require substantive length (at least 35 characters, not boilerplate header)
        if len(cleaned) >= 35 and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            clean_paras.append(cleaned)
            if len(clean_paras) >= max_passages:
                break

    # If paragraph splitting yielded fewer than 2 passages, split by sentences
    if len(clean_paras) < 2:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        for s in sentences:
            cleaned = re.sub(r"\s+", " ", s).strip()
            if len(cleaned) >= 40 and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                clean_paras.append(cleaned)
                if len(clean_paras) >= max_passages:
                    break

    return clean_paras[:max_passages]


def compare_two_documents(
    file_a: str,
    file_b: str,
    tpcg: TemporalProvenanceConflictGraph,
    upload_dir: Path,
) -> Dict[str, Any]:
    """
    Executes a side-by-side comparison of two documents.
    Returns structured comparison results, metadata, graph relationship,
    rule differences, conflict classification, outcome, and citations.
    """
    # 1. Resolve filenames and paths
    if not file_a or not file_a.strip():
        raise ValueError("First document filename ('file_a' or 'doc1') is required.")
    if not file_b or not file_b.strip():
        raise ValueError("Second document filename ('file_b' or 'doc2') is required.")

    name_a_clean = file_a.strip().strip("'\"")
    name_b_clean = file_b.strip().strip("'\"")

    # Helper to find node in graph or locate file on disk
    def find_doc_info(target_name: str) -> Dict[str, Any]:
        nodes = tpcg.get_nodes() if tpcg else []
        # Match by ID or filename
        for n in nodes:
            if (
                n["id"] == target_name
                or n.get("saved_filename") == target_name
                or n.get("original_filename") == target_name
                or n.get("filename") == target_name
            ):
                return {
                    "node_id": n["id"],
                    "saved_filename": n.get("saved_filename", n["id"]),
                    "original_filename": n.get("original_filename") or n.get("filename") or get_original_filename(n["id"]),
                    "node": n,
                    "file_path": upload_dir / n["id"] if (upload_dir / n["id"]).exists() else upload_dir / target_name,
                }

        # Check in upload directory directly
        direct_path = upload_dir / target_name
        if direct_path.exists():
            orig = get_original_filename(target_name)
            return {
                "node_id": target_name,
                "saved_filename": target_name,
                "original_filename": orig,
                "node": None,
                "file_path": direct_path,
            }

        # Check by prefix match in upload directory
        for f in upload_dir.glob("*.*"):
            if f.name == target_name or get_original_filename(f.name) == target_name:
                return {
                    "node_id": f.name,
                    "saved_filename": f.name,
                    "original_filename": get_original_filename(f.name),
                    "node": None,
                    "file_path": f,
                }

        raise FileNotFoundError(f"Document '{target_name}' not found in uploads directory or graph.")

    info_a = find_doc_info(name_a_clean)
    info_b = find_doc_info(name_b_clean)

    # 2. Extract or ensure text and metadata are populated
    def get_or_extract_node(info: Dict[str, Any]) -> Tuple[Dict[str, Any], str, DocumentMetadata]:
        saved_fn = info["saved_filename"]
        orig_fn = info["original_filename"]
        path = info["file_path"]

        # Check if already in graph with raw_text
        if tpcg and tpcg.graph.has_node(saved_fn):
            node_data = dict(tpcg.graph.nodes[saved_fn])
            raw_text = node_data.get("raw_text", "")
            if not raw_text and path.exists():
                raw_text = extract_text_from_file(path)
                node_data["raw_text"] = raw_text
                tpcg.graph.nodes[saved_fn]["raw_text"] = raw_text
        else:
            raw_text = extract_text_from_file(path) if path.exists() else ""
            meta = extract_document_metadata(raw_text, orig_fn)
            if tpcg:
                tpcg.add_document_node(
                    saved_filename=saved_fn,
                    original_filename=orig_fn,
                    metadata=meta,
                    raw_text=raw_text,
                )
                tpcg.infer_relationships()
                node_data = dict(tpcg.graph.nodes[saved_fn])
            else:
                node_data = {
                    "id": saved_fn,
                    "saved_filename": saved_fn,
                    "original_filename": orig_fn,
                    "filename": orig_fn,
                    "title": meta.document_title,
                    "effective_date": meta.effective_date,
                    "issue_date": meta.publication_or_issue_date,
                    "version": meta.version_number,
                    "document_identifier": meta.policy_or_document_identifier,
                    "scope": meta.geographic_or_organizational_scope,
                    "raw_text": raw_text,
                }

        # Create typed metadata object for clean output
        meta_obj = DocumentMetadata(
            document_title=node_data.get("title") or node_data.get("document_title"),
            effective_date=node_data.get("effective_date"),
            publication_or_issue_date=node_data.get("issue_date") or node_data.get("publication_or_issue_date"),
            version_number=node_data.get("version") or node_data.get("version_number"),
            policy_or_document_identifier=node_data.get("document_identifier") or node_data.get("policy_or_document_identifier"),
            geographic_or_organizational_scope=node_data.get("scope") or node_data.get("geographic_or_organizational_scope"),
            appears_amendment_or_replacement=bool(node_data.get("amendment_status") or node_data.get("appears_amendment_or_replacement", False)),
            referenced_parent_or_previous_policy_identifier=node_data.get("parent_policy_identifier") or node_data.get("referenced_parent_or_previous_policy_identifier"),
        )
        return node_data, raw_text, meta_obj

    node_data_a, text_a, meta_a = get_or_extract_node(info_a)
    node_data_b, text_b, meta_b = get_or_extract_node(info_b)

    id_a = info_a["saved_filename"]
    id_b = info_b["saved_filename"]
    orig_a = info_a["original_filename"]
    orig_b = info_b["original_filename"]

    # 3. Check for empty or non-extractable text (Insufficient Evidence / ABSTAIN)
    is_empty_a = len(text_a.strip()) == 0
    is_empty_b = len(text_b.strip()) == 0

    # 4. Check Graph Relationship from TPCG
    relationship = None
    relationship_direction = None
    relationship_evidence = None

    if tpcg:
        if tpcg.graph.has_edge(id_a, id_b):
            edge = tpcg.graph.get_edge_data(id_a, id_b)
            relationship = edge.get("relationship") or edge.get("type")
            relationship_direction = f"{orig_a} → {orig_b}"
            relationship_evidence = edge.get("evidence")
        elif tpcg.graph.has_edge(id_b, id_a):
            edge = tpcg.graph.get_edge_data(id_b, id_a)
            relationship = edge.get("relationship") or edge.get("type")
            relationship_direction = f"{orig_b} → {orig_a}"
            relationship_evidence = edge.get("evidence")

    # 5. Execute Conflict Detection using ConflictDetector
    detector = ConflictDetector(graph=tpcg) if tpcg else ConflictDetector()
    conflict_data = detector.analyze_pair(node_data_a, node_data_b)

    # 6. Extract representative text passages from each document
    passages_a = extract_informative_passages(text_a, max_passages=3)
    passages_b = extract_informative_passages(text_b, max_passages=3)

    # 7. Analyze structured differences
    differences: List[Dict[str, Any]] = []

    # Helper to add difference
    def add_diff(
        category: str,
        val_a: Optional[str],
        val_b: Optional[str],
        description: str,
        is_conflicting: bool,
    ):
        differences.append({
            "category": category,
            "doc_a_value": val_a if val_a else "Not specified",
            "doc_b_value": val_b if val_b else "Not specified",
            "description": description,
            "is_conflicting": is_conflicting,
        })

    # (a) Document Identifiers
    doc_id_a = meta_a.policy_or_document_identifier
    doc_id_b = meta_b.policy_or_document_identifier
    if doc_id_a or doc_id_b:
        if doc_id_a and doc_id_b and doc_id_a.upper() == doc_id_b.upper():
            add_diff(
                "Policy / Document Identifier",
                doc_id_a,
                doc_id_b,
                "Both documents share the same policy identifier, indicating versions or amendments of the same policy.",
                is_conflicting=False,
            )
        else:
            add_diff(
                "Policy / Document Identifier",
                doc_id_a,
                doc_id_b,
                "Documents have distinct policy identifiers.",
                is_conflicting=False,
            )

    # (b) Versions
    ver_a = meta_a.version_number
    ver_b = meta_b.version_number
    if ver_a or ver_b:
        is_diff = (ver_a or "").strip().lower() != (ver_b or "").strip().lower()
        desc = (
            f"Different version numbers: '{ver_a or 'unversioned'}' vs '{ver_b or 'unversioned'}'."
            if is_diff
            else f"Both documents indicate version '{ver_a}'."
        )
        add_diff("Version", ver_a, ver_b, desc, is_conflicting=is_diff and not relationship)

    # (c) Effective & Issue Dates
    eff_a = meta_a.effective_date
    eff_b = meta_b.effective_date
    if eff_a or eff_b:
        is_diff = (eff_a or "").strip() != (eff_b or "").strip()
        desc = (
            f"Different effective dates: '{eff_a or 'unspecified'}' vs '{eff_b or 'unspecified'}'."
            if is_diff
            else f"Same effective date: '{eff_a}'."
        )
        add_diff("Effective Date", eff_a, eff_b, desc, is_conflicting=False)

    issue_a = meta_a.publication_or_issue_date
    issue_b = meta_b.publication_or_issue_date
    if issue_a or issue_b:
        is_diff = (issue_a or "").strip() != (issue_b or "").strip()
        desc = (
            f"Issue / publication dates differ: '{issue_a or 'unspecified'}' vs '{issue_b or 'unspecified'}'."
            if is_diff
            else f"Same issue date: '{issue_a}'."
        )
        add_diff("Issue Date", issue_a, issue_b, desc, is_conflicting=False)

    # (d) Scope
    scope_a = meta_a.geographic_or_organizational_scope
    scope_b = meta_b.geographic_or_organizational_scope
    if scope_a or scope_b:
        is_diff = (scope_a or "").strip().upper() != (scope_b or "").strip().upper()
        if is_diff:
            add_diff(
                "Jurisdictional / Org Scope",
                scope_a,
                scope_b,
                f"Documents apply to different jurisdictional scopes ('{scope_a or 'Unspecified'}' vs '{scope_b or 'Unspecified'}'). "
                "May create boundary conflicts if operational contexts overlap.",
                is_conflicting=True,
            )
        else:
            add_diff(
                "Jurisdictional / Org Scope",
                scope_a,
                scope_b,
                f"Both documents apply to the same scope: '{scope_a}'.",
                is_conflicting=False,
            )

    # (e) Text rule provisions by topic
    rule_patterns: Dict[str, List[str]] = dict(RULE_TOPIC_PATTERNS)
    rule_patterns.update({
        "travel_allowance_entitlements": [
            r"\b(?:travel|vande\s+bharat|tejas|rajdhani|air\s+travel|train\s+tier|economy\s+class|executive\s+class|daily\s+allowance|per\s+diem|hotel\s+rates?)\b"
        ],
        "eligibility_and_thresholds": [
            r"\b(?:pay\s+level|grade\s+pay|entitled|entitlement|threshold|reimbursement\s+ceiling|allowance\s+rate)\b"
        ],
    })

    for topic_name, patterns in rule_patterns.items():
        found_a = any(re.search(pat, text_a, re.IGNORECASE) for pat in patterns)
        found_b = any(re.search(pat, text_b, re.IGNORECASE) for pat in patterns)
        if found_a and found_b:
            snip_topic_a = extract_evidence_snippet(text_a, patterns)
            snip_topic_b = extract_evidence_snippet(text_b, patterns)
            # Compare normalized snippets
            clean_a = re.sub(r"\s+", " ", snip_topic_a).strip().lower()
            clean_b = re.sub(r"\s+", " ", snip_topic_b).strip().lower()
            if clean_a != clean_b:
                has_explicit_precedence = relationship in ("SUPERSEDES", "AMENDS") or (
                    conflict_data and conflict_data.get("appears_resolvable", False)
                )
                topic_label = topic_name.replace("_", " ").title()
                add_diff(
                    f"Policy Rule Provision ({topic_label})",
                    snip_topic_a,
                    snip_topic_b,
                    (
                        f"Both documents contain specific directives on {topic_name.replace('_', ' ')}. "
                        + (
                            "Provisions differ and no explicit amendment or supersession resolves precedence between them."
                            if not has_explicit_precedence
                            else f"Provisions differ, governed by explicit {relationship or 'supersession'} relationship."
                        )
                    ),
                    is_conflicting=not has_explicit_precedence,
                )

    # (f) Conflict rules from ConflictDetector
    if conflict_data:
        c_type = conflict_data.get("conflict_type")
        c_desc = conflict_data.get("short_explanation") or conflict_data.get("explanation")
        is_resolvable = conflict_data.get("appears_resolvable", False)
        add_diff(
            f"Conflict Classification ({c_type.replace('_', ' ').title()})",
            f"Referenced in {orig_a}",
            f"Referenced in {orig_b}",
            c_desc,
            is_conflicting=not is_resolvable,
        )

    # 8. Determine Comparison Outcome: RESOLVED / CONFLICT / ABSTAIN
    outcome = "RESOLVED"
    explanation = ""

    if is_empty_a or is_empty_b:
        outcome = "ABSTAIN"
        empty_docs = []
        if is_empty_a:
            empty_docs.append(f"'{orig_a}'")
        if is_empty_b:
            empty_docs.append(f"'{orig_b}'")
        explanation = (
            f"Document {', '.join(empty_docs)} contains no extractable text. "
            "TruthGuard cannot compare documents without readable content."
        )

    elif conflict_data and conflict_data.get("conflict_type") == "insufficient_evidence":
        outcome = "ABSTAIN"
        explanation = (
            conflict_data.get("explanation")
            or "Insufficient metadata or textual evidence to establish an authoritative comparison or rule precedence."
        )

    elif conflict_data and conflict_data.get("conflict_type") in ("scope_conflict", "temporal_conflict"):
        outcome = "CONFLICT"
        explanation = (
            f"Unresolved {conflict_data['conflict_type'].replace('_', ' ')} detected between '{orig_a}' and '{orig_b}'. "
            f"{conflict_data.get('short_explanation', '')} "
            f"Precedence cannot be established: {conflict_data.get('resolvability_reason', 'Explicit precedence is missing.')}"
        )

    elif any(d.get("is_conflicting") for d in differences) and relationship not in ("SUPERSEDES", "AMENDS") and not (conflict_data and conflict_data.get("appears_resolvable")):
        outcome = "CONFLICT"
        explanation = (
            f"Potentially conflicting rules or divergent scopes detected between '{orig_a}' and '{orig_b}'. "
            "Because no explicit precedence, supersession clause, or amendment cross-reference connects these documents, "
            "TruthGuard surfaces the differences without guessing or assuming one document overrides the other."
        )

    elif conflict_data and conflict_data.get("conflict_type") == "supersession":
        outcome = "RESOLVED"
        explanation = (
            f"Precedence explicitly established: {conflict_data.get('short_explanation', '')} "
            f"{conflict_data.get('resolvability_reason', '')}"
        )

    elif relationship in ("SUPERSEDES", "AMENDS"):
        outcome = "RESOLVED"
        explanation = (
            f"Documents are linked by explicit {relationship} provenance relationship ({relationship_direction}). "
            f"Evidence: {relationship_evidence or 'Explicit parent / version cross-reference'}."
        )

    elif id_a == id_b:
        outcome = "RESOLVED"
        explanation = "Documents are identical. No differences or conflicts identified."

    else:
        # Compatible documents or no active conflicts detected
        outcome = "RESOLVED"
        explanation = (
            f"Comparison completed between '{orig_a}' and '{orig_b}'. "
            "No active policy conflicts or contradictions were detected between these documents."
        )

    # 9. Build Citations with source filenames and evidence snippets
    citations: List[Dict[str, Any]] = []

    # Citation 1: Document A
    snip_a = ""
    if conflict_data and conflict_data.get("evidence_snippets"):
        for sn in conflict_data["evidence_snippets"]:
            if sn.get("filename") == orig_a or sn.get("filename") == id_a:
                snip_a = sn.get("snippet", "")
                break
    if not snip_a and passages_a:
        snip_a = passages_a[0]
    elif not snip_a and text_a:
        snip_a = text_a[:200].strip()

    if snip_a:
        citations.append({
            "citation_id": 1,
            "filename": orig_a,
            "saved_filename": id_a,
            "title": meta_a.document_title or orig_a,
            "date": meta_a.effective_date or meta_a.publication_or_issue_date or "Date not specified",
            "snippet": snip_a,
        })

    # Citation 2: Document B
    snip_b = ""
    if conflict_data and conflict_data.get("evidence_snippets"):
        for sn in conflict_data["evidence_snippets"]:
            if sn.get("filename") == orig_b or sn.get("filename") == id_b:
                snip_b = sn.get("snippet", "")
                break
    if not snip_b and passages_b:
        snip_b = passages_b[0]
    elif not snip_b and text_b:
        snip_b = text_b[:200].strip()

    if snip_b:
        citations.append({
            "citation_id": len(citations) + 1,
            "filename": orig_b,
            "saved_filename": id_b,
            "title": meta_b.document_title or orig_b,
            "date": meta_b.effective_date or meta_b.publication_or_issue_date or "Date not specified",
            "snippet": snip_b,
        })

    # 10. Assemble structured comparison response
    return {
        "status": "success",
        "outcome": outcome,
        "relationship": relationship,
        "relationship_direction": relationship_direction,
        "relationship_evidence": relationship_evidence,
        "document_a": {
            "filename": orig_a,
            "saved_filename": id_a,
            "is_empty": is_empty_a,
            "metadata": {
                "document_title": meta_a.document_title or "Untitled Document",
                "version": meta_a.version_number or "Not specified",
                "issue_date": meta_a.publication_or_issue_date or "Not specified",
                "effective_date": meta_a.effective_date or "Not specified",
                "scope": meta_a.geographic_or_organizational_scope or "Not specified",
                "policy_or_document_identifier": meta_a.policy_or_document_identifier or "Not specified",
            },
            "passages": passages_a,
        },
        "document_b": {
            "filename": orig_b,
            "saved_filename": id_b,
            "is_empty": is_empty_b,
            "metadata": {
                "document_title": meta_b.document_title or "Untitled Document",
                "version": meta_b.version_number or "Not specified",
                "issue_date": meta_b.publication_or_issue_date or "Not specified",
                "effective_date": meta_b.effective_date or "Not specified",
                "scope": meta_b.geographic_or_organizational_scope or "Not specified",
                "policy_or_document_identifier": meta_b.policy_or_document_identifier or "Not specified",
            },
            "passages": passages_b,
        },
        "differences": differences,
        "differences_count": len(differences),
        "conflict": conflict_data,
        "explanation": explanation,
        "citations": citations,
    }

