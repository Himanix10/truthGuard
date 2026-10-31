"""
Conflict Detection Module for TruthGuard-Chronos.

Identifies, analyzes, and classifies potential policy conflicts between documents
using the Temporal-Provenance Conflict Graph (TPCG) and document metadata.

Detects and classifies:
  1. Supersession: Newer document explicitly amends or supersedes an older one.
  2. Scope conflict: Documents contain potentially conflicting rules with different or unclear scopes.
  3. Temporal conflict: Overlapping validity periods with conflicting directives without explicit supersession.
  4. Insufficient evidence: Metadata or text is insufficient to establish or resolve a conflict.
"""

import re
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Set, Union
from pydantic import BaseModel, Field

try:
    from app.graph.tpcg import (
        TemporalProvenanceConflictGraph,
        parse_date_for_comparison,
        parse_version_tuple,
        to_json_safe,
    )
except ImportError:
    from tpcg import (
        TemporalProvenanceConflictGraph,
        parse_date_for_comparison,
        parse_version_tuple,
        to_json_safe,
    )


# Common policy rule topic keywords for deterministic rule matching
RULE_TOPIC_PATTERNS = {
    "encryption": [
        r"\b(?:encryption|encrypt|aes-?\d+|tls\s*\d+\.\d+|cryptographic|cipher)\b",
    ],
    "data_retention": [
        r"\b(?:retained?|retention|retain|delete|deletion|archive|archival|storage\s+period)\b",
    ],
    "passwords_authentication": [
        r"\b(?:passwords?|mfa|multi-factor|two-factor|authentication|credentials?|login)\b",
    ],
    "access_control": [
        r"\b(?:access\s+control|permissions?|authorization|privileged\s+access|least\s+privilege)\b",
    ],
    "remote_work": [
        r"\b(?:remote\s+work|telecommuting|work\s+from\s+home|wfh|hybrid\s+work)\b",
    ],
    "incident_reporting": [
        r"\b(?:incident\s+report|breach\s+notification|security\s+incident|report\s+within)\b",
    ],
    "operations_procedure": [
        r"\b(?:standard\s+operating\s+procedure|operational\s+guidelines?|standard\s+operations?)\b",
    ],
    "governance_compliance": [
        r"\b(?:governance|compliance|regulatory|gdpr|hipaa|data\s+protection)\b",
    ],
}


def extract_evidence_snippet(text: str, keywords: List[str], max_length: int = 240) -> str:
    """Extracts a relevant context snippet from text around matching keywords."""
    if not text:
        return ""
    text_clean = text.strip()
    for kw in keywords:
        match = re.search(r"\b" + re.escape(kw) + r"\b", text_clean, re.IGNORECASE)
        if match:
            start = max(0, match.start() - 50)
            end = min(len(text_clean), match.end() + 150)
            snippet = text_clean[start:end].strip()
            # Clean up linebreaks
            snippet = re.sub(r"\s+", " ", snippet)
            return snippet
    # Fallback to first lines
    first_chunk = text_clean[:max_length].strip()
    return re.sub(r"\s+", " ", first_chunk)


class ConflictDetector:
    """
    Detects and classifies document policy conflicts using TPCG nodes, edges,
    and rule-based text comparison.
    """

    def __init__(self, graph: Optional[TemporalProvenanceConflictGraph] = None):
        self._graph = graph

    @property
    def graph(self) -> Optional[TemporalProvenanceConflictGraph]:
        return self._graph

    @graph.setter
    def graph(self, graph: TemporalProvenanceConflictGraph):
        self._graph = graph

    def get_candidate_document_pairs(
        self, target_files: Optional[List[str]] = None
    ) -> List[Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]]:
        """
        Extracts candidate document pairs from the graph using edges, shared identifiers,
        and related policy topics. Returns list of (doc_a, doc_b, edge_data).
        """
        if not self._graph:
            return []

        nodes = self._graph.get_nodes()
        node_map = {n["id"]: n for n in nodes}

        # Filter by target_files if provided
        if target_files:
            clean_targets = {t.strip().upper() for t in target_files if t and t.strip()}
            filtered_nodes = [
                n
                for n in nodes
                if n["id"].upper() in clean_targets
                or (n.get("original_filename") and n["original_filename"].upper() in clean_targets)
                or (n.get("filename") and n["filename"].upper() in clean_targets)
            ]
            node_map = {n["id"]: n for n in filtered_nodes}

        pairs: List[Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]] = []
        seen_pairs: Set[Tuple[str, str]] = set()

        # 1. Pairs connected by directed edges in TPCG
        for u, v, edge_data in self._graph.graph.edges(data=True):
            if u not in node_map or v not in node_map:
                continue
            pair_key = tuple(sorted([u, v]))
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                # Keep chronological / directed orientation: source first, target second
                pairs.append((node_map[u], node_map[v], edge_data))

        # 2. Pairs sharing document identifiers or matching policy titles
        node_list = list(node_map.values())
        for i in range(len(node_list)):
            for j in range(i + 1, len(node_list)):
                doc_a = node_list[i]
                doc_b = node_list[j]
                u_id = doc_a["id"]
                v_id = doc_b["id"]
                pair_key = tuple(sorted([u_id, v_id]))
                if pair_key in seen_pairs:
                    continue

                id_a = (doc_a.get("document_identifier") or "").strip().upper()
                id_b = (doc_b.get("document_identifier") or "").strip().upper()
                title_a = (doc_a.get("title") or "").strip().upper()
                title_b = (doc_b.get("title") or "").strip().upper()

                # Share document identifier
                same_id = bool(id_a and id_b and id_a == id_b)
                # Share explicit policy title
                same_title = bool(title_a and title_b and len(title_a) > 5 and title_a == title_b)

                # Cross-reference in parent_policy_identifier
                parent_a = (doc_a.get("parent_policy_identifier") or "").strip().upper()
                parent_b = (doc_b.get("parent_policy_identifier") or "").strip().upper()
                cross_ref = bool(
                    (parent_a and id_b and parent_a == id_b)
                    or (parent_b and id_a and parent_b == id_a)
                )

                if same_id or same_title or cross_ref:
                    seen_pairs.add(pair_key)
                    pairs.append((doc_a, doc_b, None))

        # 3. Pairs with matching domain topics or scope divergence
        for i in range(len(node_list)):
            for j in range(i + 1, len(node_list)):
                doc_a = node_list[i]
                doc_b = node_list[j]
                pair_key = tuple(sorted([doc_a["id"], doc_b["id"]]))
                if pair_key in seen_pairs:
                    continue

                topic_overlap = self._check_topic_overlap(doc_a, doc_b)
                if topic_overlap:
                    seen_pairs.add(pair_key)
                    pairs.append((doc_a, doc_b, None))

        # 4. Check isolated documents with missing metadata (for insufficient_evidence)
        for doc in node_list:
            if not doc.get("document_identifier") and not doc.get("effective_date"):
                # Pair with at least one substantive doc to report insufficient evidence if candidate
                for other in node_list:
                    if other["id"] == doc["id"]:
                        continue
                    pair_key = tuple(sorted([doc["id"], other["id"]]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        pairs.append((doc, other, None))
                        break

        return pairs

    def _check_topic_overlap(self, doc_a: Dict[str, Any], doc_b: Dict[str, Any]) -> Optional[str]:
        """Checks if two documents share key policy domain topics."""
        text_a = f"{doc_a.get('title') or ''} {doc_a.get('filename') or ''}".lower()
        text_b = f"{doc_b.get('title') or ''} {doc_b.get('filename') or ''}".lower()

        for topic, patterns in RULE_TOPIC_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, text_a, re.I) and re.search(pat, text_b, re.I):
                    return topic
        return None

    def analyze_pair(
        self,
        doc_a: Dict[str, Any],
        doc_b: Dict[str, Any],
        edge_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Analyzes a candidate document pair and classifies the conflict into one of:
          1. supersession
          2. scope_conflict
          3. temporal_conflict
          4. insufficient_evidence
        Returns a structured conflict dictionary or None.
        """
        # Retrieve full nodes from graph to access raw text
        node_a = self._graph.graph.nodes.get(doc_a["id"], doc_a) if self._graph else doc_a
        node_b = self._graph.graph.nodes.get(doc_b["id"], doc_b) if self._graph else doc_b

        text_a = node_a.get("raw_text", "")
        text_b = node_b.get("raw_text", "")

        name_a = node_a.get("original_filename") or node_a.get("filename") or node_a["id"]
        name_b = node_b.get("original_filename") or node_b.get("filename") or node_b["id"]
        id_a = node_a.get("document_identifier")
        id_b = node_b.get("document_identifier")

        # Determine edge relationship if exists
        rel_type = None
        if edge_data:
            rel_type = edge_data.get("relationship")
        elif self._graph:
            if self._graph.graph.has_edge(node_a["id"], node_b["id"]):
                rel_type = self._graph.graph.get_edge_data(node_a["id"], node_b["id"]).get("relationship")
            elif self._graph.graph.has_edge(node_b["id"], node_a["id"]):
                rel_type = self._graph.graph.get_edge_data(node_b["id"], node_a["id"]).get("relationship")
                # Swap orientation so source is doc_a
                node_a, node_b = node_b, node_a
                text_a, text_b = text_b, text_a
                name_a, name_b = name_b, name_a
                id_a, id_b = id_b, id_a

        # -------------------------------------------------------------
        # CASE 4: Insufficient Evidence
        # Check if text is missing, empty, or metadata lacks basic attributes
        # -------------------------------------------------------------
        has_substantive_text_a = bool(text_a and len(text_a.strip()) > 30)
        has_substantive_text_b = bool(text_b and len(text_b.strip()) > 30)
        has_metadata_a = bool(id_a or node_a.get("effective_date") or node_a.get("title"))
        has_metadata_b = bool(id_b or node_b.get("effective_date") or node_b.get("title"))

        if not has_substantive_text_a or not has_substantive_text_b or not has_metadata_a or not has_metadata_b:
            empty_name = name_a if not has_substantive_text_a or not has_metadata_a else name_b
            snippet_a = text_a[:160].strip() if text_a else "[Empty document / No extractable text found]"
            snippet_b = text_b[:160].strip() if text_b else "[Empty document / No extractable text found]"

            return {
                "conflict_type": "insufficient_evidence",
                "type": "insufficient_evidence",
                "involved_filenames": [name_a, name_b],
                "involved_saved_filenames": [node_a["id"], node_b["id"]],
                "short_explanation": (
                    f"Document '{empty_name}' lacks sufficient metadata (missing effective dates, identifiers, or scopes) "
                    "or extractable policy text to confirm or resolve a conflict."
                ),
                "explanation": (
                    f"Document '{empty_name}' lacks sufficient metadata (missing effective dates, identifiers, or scopes) "
                    "or extractable policy text to confirm or resolve a conflict."
                ),
                "evidence_snippets": [
                    {"filename": name_a, "snippet": snippet_a},
                    {"filename": name_b, "snippet": snippet_b},
                ],
                "appears_resolvable": False,
                "resolvable": False,
                "resolvability_reason": (
                    "Metadata or document text is insufficient to establish an actionable rule contradiction "
                    "or to determine authoritative precedence."
                ),
            }

        # -------------------------------------------------------------
        # CASE 1: Supersession
        # Newer document explicitly amends or supersedes an older one
        # -------------------------------------------------------------
        if rel_type in ("SUPERSEDES", "AMENDS"):
            is_supersede = rel_type == "SUPERSEDES"
            action_verb = "supersedes" if is_supersede else "amends"
            past_verb = "superseded" if is_supersede else "amended"

            snippet_a = extract_evidence_snippet(
                text_a, [id_b or "", "supersedes", "amends", "replaces", "version"]
            )
            snippet_b = extract_evidence_snippet(
                text_b, [id_b or "", "version", "scope", "effective", "policy"]
            )

            explanation = (
                f"Document '{name_a}' explicitly {action_verb} '{name_b}' "
                f"({id_b or 'earlier policy'}). "
                f"The newer policy establishes governing provisions that replace or amend {past_verb} terms."
            )

            return {
                "conflict_type": "supersession",
                "type": "supersession",
                "involved_filenames": [name_a, name_b],
                "involved_saved_filenames": [node_a["id"], node_b["id"]],
                "short_explanation": explanation,
                "explanation": explanation,
                "evidence_snippets": [
                    {"filename": name_a, "snippet": snippet_a},
                    {"filename": name_b, "snippet": snippet_b},
                ],
                "appears_resolvable": True,
                "resolvable": True,
                "resolvability_reason": (
                    f"Explicit metadata and textual evidence ('{action_verb} {id_b or name_b}') "
                    f"authoritatively establishes that '{name_a}' governs over '{name_b}'."
                ),
            }

        # -------------------------------------------------------------
        # Check Scope Divergence
        # -------------------------------------------------------------
        scope_a = (node_a.get("scope") or "").strip()
        scope_b = (node_b.get("scope") or "").strip()
        scopes_differ = bool(scope_a and scope_b and scope_a.upper() != scope_b.upper())
        scope_unclear = bool(not scope_a or not scope_b)

        # -------------------------------------------------------------
        # CASE 2: Scope Conflict
        # Potentially conflicting rules with different or unclear scopes
        # -------------------------------------------------------------
        if scopes_differ or (scope_unclear and (id_a == id_b or rel_type == "SAME_POLICY")):
            snippet_a = extract_evidence_snippet(text_a, ["scope", scope_a or "global", "policy", "must"])
            snippet_b = extract_evidence_snippet(text_b, ["scope", scope_b or "regional", "policy", "must"])

            display_scope_a = scope_a or "Unspecified Scope"
            display_scope_b = scope_b or "Unspecified Scope"

            explanation = (
                f"Documents contain diverging requirements under different or unaligned scopes "
                f"('{display_scope_a}' vs '{display_scope_b}'). Neither document explicitly designates "
                "jurisdictional hierarchy or precedence."
            )

            return {
                "conflict_type": "scope_conflict",
                "type": "scope_conflict",
                "involved_filenames": [name_a, name_b],
                "involved_saved_filenames": [node_a["id"], node_b["id"]],
                "short_explanation": explanation,
                "explanation": explanation,
                "evidence_snippets": [
                    {"filename": name_a, "snippet": snippet_a},
                    {"filename": name_b, "snippet": snippet_b},
                ],
                "appears_resolvable": False,
                "resolvable": False,
                "resolvability_reason": (
                    f"Scopes differ ('{display_scope_a}' vs '{display_scope_b}') without an explicit clause "
                    "specifying which policy takes precedence in overlapping contexts."
                ),
            }

        # -------------------------------------------------------------
        # Check Temporal Overlap
        # -------------------------------------------------------------
        date_a = parse_date_for_comparison(node_a.get("effective_date") or node_a.get("issue_date"))
        date_b = parse_date_for_comparison(node_b.get("effective_date") or node_b.get("issue_date"))
        both_dates_present = bool(date_a and date_b)

        # -------------------------------------------------------------
        # CASE 3: Temporal Conflict
        # Overlapping validity periods and potentially conflicting rules,
        # where newer document lacks explicit amendment/supersession.
        # -------------------------------------------------------------
        if both_dates_present or id_a == id_b or rel_type == "SAME_POLICY":
            # If dates are present, both policies are active without explicit revocation
            date_a_str = node_a.get("effective_date") or node_a.get("issue_date") or "Active"
            date_b_str = node_b.get("effective_date") or node_b.get("issue_date") or "Active"

            snippet_a = extract_evidence_snippet(text_a, ["effective", "version", "date", "must", "standard"])
            snippet_b = extract_evidence_snippet(text_b, ["effective", "version", "date", "must", "standard"])

            explanation = (
                f"Documents share concurrent active validity periods ({date_a_str} and {date_b_str}) "
                "with diverging policy directives, but lack explicit amendment or supersession evidence. "
                "Under TruthGuard rules, a newer document does not automatically override an older one without explicit evidence."
            )

            return {
                "conflict_type": "temporal_conflict",
                "type": "temporal_conflict",
                "involved_filenames": [name_a, name_b],
                "involved_saved_filenames": [node_a["id"], node_b["id"]],
                "short_explanation": explanation,
                "explanation": explanation,
                "evidence_snippets": [
                    {"filename": name_a, "snippet": snippet_a},
                    {"filename": name_b, "snippet": snippet_b},
                ],
                "appears_resolvable": False,
                "resolvable": False,
                "resolvability_reason": (
                    "No explicit supersession or amendment metadata connects these documents. "
                    "A newer date alone cannot automatically resolve which policy provision governs."
                ),
            }

        # If none of the conflict conditions are met
        return None

    def detect_conflicts(
        self, target_files: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Executes conflict detection across candidate document pairs in the graph.
        Returns list of structured conflict records.
        """
        candidate_pairs = self.get_candidate_document_pairs(target_files)
        conflicts: List[Dict[str, Any]] = []
        seen_conflict_keys: Set[Tuple[str, str, str]] = set()

        for idx, (doc_a, doc_b, edge_data) in enumerate(candidate_pairs, start=1):
            conflict = self.analyze_pair(doc_a, doc_b, edge_data)
            if conflict:
                # Deduplicate by (sorted filenames, conflict_type)
                pair_key = (
                    tuple(sorted(conflict["involved_saved_filenames"])),
                    conflict["conflict_type"],
                )
                if pair_key not in seen_conflict_keys:
                    seen_conflict_keys.add(pair_key)
                    conflict["conflict_id"] = f"conflict_{len(conflicts) + 1:02d}"
                    conflicts.append(conflict)

        return conflicts

