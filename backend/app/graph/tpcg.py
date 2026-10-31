"""
Temporal-Provenance Conflict Graph (TPCG) Module for TruthGuard-Chronos.

Constructs and queries an in-memory directed graph representing temporal
and provenance relationships across uploaded policy documents using NetworkX.
"""

import re
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Union, Set
import networkx as nx
import pymupdf as fitz

try:
    from app.ingestion.metadata_extractor import extract_document_metadata, DocumentMetadata
except ImportError:
    from metadata_extractor import extract_document_metadata, DocumentMetadata


def get_original_filename(saved_filename: str) -> str:
    """Extracts original filename if saved with 8-character hex prefix."""
    if "_" in saved_filename:
        prefix, remainder = saved_filename.split("_", 1)
        if len(prefix) == 8 and all(c in "0123456789abcdefABCDEF" for c in prefix):
            return remainder
    return saved_filename


def extract_text_from_file(file_path: Path) -> str:
    """Extracts text from PDF or TXT files."""
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        try:
            doc = fitz.open(file_path)
            try:
                pages = [page.get_text() for page in doc]
                return "".join(pages)
            finally:
                doc.close()
        except Exception:
            return ""
    elif ext == ".txt":
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return ""
    return ""


def parse_date_for_comparison(date_str: Optional[str]) -> Optional[datetime.date]:
    """Parses a date string into a comparable datetime.date object."""
    if not date_str or not isinstance(date_str, str):
        return None
    cleaned = date_str.strip()
    date_formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %Y",
        "%b %Y",
        "%Y",
    )
    for fmt in date_formats:
        try:
            return datetime.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    # Fallback: search for 4-digit year
    m = re.search(r"\b(19\d\d|20\d\d)\b", cleaned)
    if m:
        try:
            return datetime.date(int(m.group(1)), 1, 1)
        except Exception:
            pass
    return None


def parse_version_tuple(version_str: Optional[str]) -> Optional[Tuple[int, ...]]:
    """Extracts integer numbers from a version string for comparison (e.g., 'v2.1' -> (2, 1))."""
    if not version_str or not isinstance(version_str, str):
        return None
    numbers = re.findall(r"\d+", version_str)
    if numbers:
        return tuple(int(n) for n in numbers)
    return None


def to_json_safe(val: Any) -> Any:
    """Ensures that all objects are serializable into standard JSON types."""
    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.isoformat()
    if isinstance(val, Path):
        return str(val)
    if isinstance(val, (list, tuple, set)):
        return [to_json_safe(item) for item in val]
    if isinstance(val, dict):
        return {str(k): to_json_safe(v) for k, v in val.items()}
    if hasattr(val, "model_dump"):
        return to_json_safe(val.model_dump())
    if hasattr(val, "dict"):
        return to_json_safe(val.dict())
    return str(val)


class TemporalProvenanceConflictGraph:
    """
    Temporal-Provenance Conflict Graph (TPCG) for policy documents.
    Constructs nodes from documents and metadata, infers directed relationships,
    and supports provenance and lineage queries.
    """

    def __init__(self):
        self._graph = nx.DiGraph()

    @property
    def graph(self) -> nx.DiGraph:
        """Returns the underlying NetworkX DiGraph instance."""
        return self._graph

    @property
    def node_count(self) -> int:
        """Number of document nodes in graph."""
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        """Number of directed relationship edges in graph."""
        return self._graph.number_of_edges()

    def clear(self) -> None:
        """Resets the graph to an empty state."""
        self._graph.clear()

    def add_document_node(
        self,
        saved_filename: str,
        original_filename: Optional[str] = None,
        metadata: Optional[Union[DocumentMetadata, Dict[str, Any]]] = None,
        raw_text: Optional[str] = None,
    ) -> str:
        """
        Adds or updates a document node in the graph with its metadata attributes.
        Returns the node ID (saved_filename).
        """
        orig_name = original_filename or get_original_filename(saved_filename)
        
        meta_dict: Dict[str, Any] = {}
        if metadata:
            if hasattr(metadata, "model_dump"):
                meta_dict = metadata.model_dump()
            elif isinstance(metadata, dict):
                meta_dict = metadata

        title = meta_dict.get("document_title")
        eff_date = meta_dict.get("effective_date")
        issue_date = meta_dict.get("publication_or_issue_date")
        version = meta_dict.get("version_number")
        doc_id = meta_dict.get("policy_or_document_identifier")
        scope = meta_dict.get("geographic_or_organizational_scope")
        amend_status = bool(meta_dict.get("appears_amendment_or_replacement", False))
        parent_id = meta_dict.get("referenced_parent_or_previous_policy_identifier")

        node_attributes = {
            "id": saved_filename,
            "filename": orig_name,
            "saved_filename": saved_filename,
            "original_filename": orig_name,
            "title": title,
            "document_title": title,
            "effective_date": eff_date,
            "issue_date": issue_date,
            "publication_or_issue_date": issue_date,
            "version": version,
            "version_number": version,
            "document_identifier": doc_id,
            "policy_or_document_identifier": doc_id,
            "scope": scope,
            "geographic_or_organizational_scope": scope,
            "amendment_status": amend_status,
            "appears_amendment_or_replacement": amend_status,
            "parent_policy_identifier": parent_id,
            "referenced_parent_or_previous_policy_identifier": parent_id,
            "raw_text": raw_text or "",
        }

        self._graph.add_node(saved_filename, **node_attributes)
        return saved_filename

    def remove_document_node(self, node_id: str) -> bool:
        """Removes a document node and its connected edges."""
        if self._graph.has_node(node_id):
            self._graph.remove_node(node_id)
            return True
        return False

    def infer_relationships(self) -> None:
        """
        Infers directed edges between document nodes strictly based on explicit metadata.
        Edges created:
          - AMENDS: Explicit amendment to another document/policy
          - SUPERSEDES: Explicit supersession or replacement of another document/policy
          - SAME_POLICY: Two documents belonging to the same policy identifier or title
          - RELATED_TO: Explicit cross-reference or hierarchical parent policy reference
        Does not invent relationships when metadata is missing.
        """
        # Clear existing edges before re-inferring
        self._graph.remove_edges_from(list(self._graph.edges()))

        nodes = list(self._graph.nodes(data=True))
        if not nodes:
            return

        # Build lookup indices for fast, accurate matching
        id_to_nodes: Dict[str, List[str]] = {}
        filename_to_nodes: Dict[str, List[str]] = {}
        title_to_nodes: Dict[str, List[str]] = {}

        for n_id, data in nodes:
            doc_ident = data.get("document_identifier")
            if doc_ident and isinstance(doc_ident, str) and doc_ident.strip():
                clean_id = doc_ident.strip().upper()
                id_to_nodes.setdefault(clean_id, []).append(n_id)

            orig_name = data.get("original_filename")
            if orig_name and isinstance(orig_name, str) and orig_name.strip():
                clean_fname = orig_name.strip().upper()
                filename_to_nodes.setdefault(clean_fname, []).append(n_id)
                stem = Path(orig_name).stem.strip().upper()
                if stem != clean_fname:
                    filename_to_nodes.setdefault(stem, []).append(n_id)

            title = data.get("title")
            if title and isinstance(title, str) and len(title.strip()) > 3:
                clean_title = title.strip().upper()
                title_to_nodes.setdefault(clean_title, []).append(n_id)

        # 1. Check Explicit Parent / Referenced Policy Identifiers
        for n_id, data in nodes:
            parent_ref = data.get("parent_policy_identifier")
            if not parent_ref or not isinstance(parent_ref, str) or not parent_ref.strip():
                continue

            clean_ref = parent_ref.strip().upper()
            raw_text = data.get("raw_text", "")
            title = data.get("title") or ""
            context_search = f"{title}\n{raw_text[:2500]}"

            # Find matching target nodes
            target_ids: Set[str] = set()

            # Match by document identifier
            if clean_ref in id_to_nodes:
                target_ids.update(id_to_nodes[clean_ref])

            # Match by filename or stem
            if clean_ref in filename_to_nodes:
                target_ids.update(filename_to_nodes[clean_ref])

            # Also check partial/substring identifier matches (e.g. DG-GLOBAL-001 in DG-GLOBAL-001-V1)
            for registered_id, reg_nodes in id_to_nodes.items():
                if registered_id == clean_ref or clean_ref.startswith(registered_id) or registered_id.startswith(clean_ref):
                    target_ids.update(reg_nodes)

            # Do not link a node to itself
            target_ids.discard(n_id)

            for target_id in target_ids:
                # Determine relationship type
                # Check for explicit amendment keywords
                is_amendment = bool(
                    re.search(
                        r"\b(?:amend|amends|amended|amendment|addendum)\b",
                        context_search,
                        re.IGNORECASE,
                    )
                )

                # Check for explicit supersession keywords
                is_superseding = bool(
                    re.search(
                        r"\b(?:supersede|supersedes|superseded|replace|replaces|replacement|substitute|substitutes|override|overrides|revises)\b",
                        context_search,
                        re.IGNORECASE,
                    )
                )

                if is_amendment:
                    rel_type = "AMENDS"
                elif is_superseding:
                    rel_type = "SUPERSEDES"
                elif data.get("amendment_status"):
                    # Amendment status flagged True
                    if re.search(r"\b(?:supersede|replace)\b", context_search, re.IGNORECASE):
                        rel_type = "SUPERSEDES"
                    else:
                        rel_type = "AMENDS"
                else:
                    # Referenced parent policy without explicit amendment or superseding
                    rel_type = "RELATED_TO"

                self._graph.add_edge(
                    n_id,
                    target_id,
                    relationship=rel_type,
                    type=rel_type,
                    evidence=f"Explicit reference to '{parent_ref}'",
                )

        # 2. Check SAME_POLICY for documents sharing the same document identifier
        for doc_ident, member_ids in id_to_nodes.items():
            if len(member_ids) < 2:
                continue

            # Compare pairs within the same policy identifier
            for i in range(len(member_ids)):
                for j in range(i + 1, len(member_ids)):
                    u_id = member_ids[i]
                    v_id = member_ids[j]

                    # Skip if an edge already exists
                    if self._graph.has_edge(u_id, v_id) or self._graph.has_edge(v_id, u_id):
                        continue

                    u_data = self._graph.nodes[u_id]
                    v_data = self._graph.nodes[v_id]

                    # Compare versions and dates to establish temporal provenance direction (newer -> older)
                    order = self._compare_documents_chronologically(u_data, v_data)

                    if order > 0:
                        # u is newer than v: u -> v
                        self._graph.add_edge(
                            u_id,
                            v_id,
                            relationship="SAME_POLICY",
                            type="SAME_POLICY",
                            evidence=f"Shared policy identifier '{doc_ident}'",
                        )
                    elif order < 0:
                        # v is newer than u: v -> u
                        self._graph.add_edge(
                            v_id,
                            u_id,
                            relationship="SAME_POLICY",
                            type="SAME_POLICY",
                            evidence=f"Shared policy identifier '{doc_ident}'",
                        )
                    else:
                        # Indeterminate chronological order: connect both
                        self._graph.add_edge(
                            u_id,
                            v_id,
                            relationship="SAME_POLICY",
                            type="SAME_POLICY",
                            evidence=f"Shared policy identifier '{doc_ident}'",
                        )
                        self._graph.add_edge(
                            v_id,
                            u_id,
                            relationship="SAME_POLICY",
                            type="SAME_POLICY",
                            evidence=f"Shared policy identifier '{doc_ident}'",
                        )

        # 3. Check Body Text Cross-References for RELATED_TO / AMENDS / SUPERSEDES
        for n_id, data in nodes:
            raw_text = data.get("raw_text", "")
            if not raw_text or len(raw_text) < 10:
                continue

            u_doc_ident = (data.get("document_identifier") or "").strip().upper()

            for doc_ident, target_node_ids in id_to_nodes.items():
                # Avoid trivial matches (require length >= 4)
                if len(doc_ident) < 4:
                    continue

                # Skip matching against the node's own identifier
                if u_doc_ident and doc_ident == u_doc_ident:
                    continue

                for t_id in target_node_ids:
                    if t_id == n_id:
                        continue
                    if self._graph.has_edge(n_id, t_id):
                        continue

                    # Look for explicit identifier mentions in text
                    pattern = r"\b" + re.escape(doc_ident) + r"\b"
                    match = re.search(pattern, raw_text, re.IGNORECASE)
                    if match:
                        start_pos = max(0, match.start() - 100)
                        end_pos = min(len(raw_text), match.end() + 100)
                        snippet = raw_text[start_pos:end_pos]

                        if re.search(r"\b(?:amend|amends|amended|amendment)\b", snippet, re.IGNORECASE):
                            rel_type = "AMENDS"
                        elif re.search(r"\b(?:supersede|supersedes|replaces|replacement)\b", snippet, re.IGNORECASE):
                            rel_type = "SUPERSEDES"
                        else:
                            rel_type = "RELATED_TO"

                        self._graph.add_edge(
                            n_id,
                            t_id,
                            relationship=rel_type,
                            type=rel_type,
                            evidence=f"Explicit textual reference to '{doc_ident}'",
                        )

    def _compare_documents_chronologically(self, doc_a: Dict[str, Any], doc_b: Dict[str, Any]) -> int:
        """
        Compares two document records to determine which is newer.
        Returns:
          1 if doc_a is strictly newer than doc_b
         -1 if doc_b is strictly newer than doc_a
          0 if indeterminate or equal
        """
        # 1. Compare version tuples
        v_a = parse_version_tuple(doc_a.get("version"))
        v_b = parse_version_tuple(doc_b.get("version"))
        if v_a and v_b and v_a != v_b:
            return 1 if v_a > v_b else -1

        # 2. Compare effective dates
        eff_a = parse_date_for_comparison(doc_a.get("effective_date"))
        eff_b = parse_date_for_comparison(doc_b.get("effective_date"))
        if eff_a and eff_b and eff_a != eff_b:
            return 1 if eff_a > eff_b else -1

        # 3. Compare issue/publication dates
        iss_a = parse_date_for_comparison(doc_a.get("issue_date"))
        iss_b = parse_date_for_comparison(doc_b.get("issue_date"))
        if iss_a and iss_b and iss_a != iss_b:
            return 1 if iss_a > iss_b else -1

        return 0

    def build_from_directory(self, upload_dir: Path) -> Dict[str, Any]:
        """
        Rebuilds the graph from all uploaded documents in the given directory.
        Reads text, extracts metadata, creates nodes, and infers edges.
        """
        self.clear()
        if not upload_dir.exists() or not upload_dir.is_dir():
            return self.to_dict()

        allowed_exts = {".pdf", ".txt"}
        for file_path in sorted(upload_dir.iterdir()):
            if not file_path.is_file():
                continue
            if file_path.name.startswith("."):
                continue
            if file_path.suffix.lower() not in allowed_exts:
                continue

            text = extract_text_from_file(file_path)
            orig_name = get_original_filename(file_path.name)
            meta = extract_document_metadata(text, orig_name)

            self.add_document_node(
                saved_filename=file_path.name,
                original_filename=orig_name,
                metadata=meta,
                raw_text=text,
            )

        self.infer_relationships()
        return self.to_dict()

    def get_nodes(self) -> List[Dict[str, Any]]:
        """Returns JSON-safe list of all node dictionaries with required metadata attributes."""
        nodes = []
        for node_id, data in self._graph.nodes(data=True):
            node_dict = {
                "id": node_id,
                "filename": data.get("filename"),
                "saved_filename": data.get("saved_filename"),
                "original_filename": data.get("original_filename"),
                "title": data.get("title"),
                "document_title": data.get("document_title"),
                "effective_date": data.get("effective_date"),
                "issue_date": data.get("issue_date"),
                "publication_or_issue_date": data.get("publication_or_issue_date"),
                "version": data.get("version"),
                "version_number": data.get("version_number"),
                "document_identifier": data.get("document_identifier"),
                "policy_or_document_identifier": data.get("policy_or_document_identifier"),
                "scope": data.get("scope"),
                "geographic_or_organizational_scope": data.get("geographic_or_organizational_scope"),
                "amendment_status": data.get("amendment_status"),
                "appears_amendment_or_replacement": data.get("appears_amendment_or_replacement"),
                "parent_policy_identifier": data.get("parent_policy_identifier"),
                "referenced_parent_or_previous_policy_identifier": data.get("referenced_parent_or_previous_policy_identifier"),
            }
            nodes.append(to_json_safe(node_dict))
        return nodes

    def get_edges(self) -> List[Dict[str, Any]]:
        """Returns JSON-safe list of all directed edge dictionaries."""
        edges = []
        for u, v, data in self._graph.edges(data=True):
            u_node = self._graph.nodes.get(u, {})
            v_node = self._graph.nodes.get(v, {})
            edge_dict = {
                "source": u,
                "target": v,
                "relationship": data.get("relationship", "RELATED_TO"),
                "type": data.get("type", data.get("relationship", "RELATED_TO")),
                "source_identifier": u_node.get("document_identifier"),
                "target_identifier": v_node.get("document_identifier"),
                "evidence": data.get("evidence"),
            }
            edges.append(to_json_safe(edge_dict))
        return edges

    def to_dict(self) -> Dict[str, Any]:
        """Returns the full graph representation as a JSON-safe dictionary."""
        return {
            "nodes": self.get_nodes(),
            "edges": self.get_edges(),
            "node_count": self.node_count,
            "edge_count": self.edge_count,
        }

    # Query methods
    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Finds a specific node by ID (saved filename)."""
        if self._graph.has_node(node_id):
            data = self._graph.nodes[node_id]
            node_dict = {
                "id": node_id,
                "filename": data.get("filename"),
                "saved_filename": data.get("saved_filename"),
                "original_filename": data.get("original_filename"),
                "title": data.get("title"),
                "effective_date": data.get("effective_date"),
                "issue_date": data.get("issue_date"),
                "version": data.get("version"),
                "document_identifier": data.get("document_identifier"),
                "scope": data.get("scope"),
                "amendment_status": data.get("amendment_status"),
                "parent_policy_identifier": data.get("parent_policy_identifier"),
            }
            return to_json_safe(node_dict)
        return None

    def find_nodes_by_identifier(self, identifier: str) -> List[Dict[str, Any]]:
        """Finds all nodes whose document identifier matches the query string."""
        if not identifier:
            return []
        clean = identifier.strip().upper()
        matching = []
        for n in self.get_nodes():
            doc_id = n.get("document_identifier")
            if doc_id and str(doc_id).strip().upper() == clean:
                matching.append(n)
        return matching

    def get_successors(self, node_id: str) -> List[Dict[str, Any]]:
        """Returns all documents that this document points to (targets of outgoing edges)."""
        if not self._graph.has_node(node_id):
            return []
        results = []
        for succ in self._graph.successors(node_id):
            edge_data = self._graph.get_edge_data(node_id, succ) or {}
            target_node = self.get_node(succ)
            results.append({
                "target": succ,
                "relationship": edge_data.get("relationship"),
                "target_node": target_node,
            })
        return results

    def get_predecessors(self, node_id: str) -> List[Dict[str, Any]]:
        """Returns all documents that point to this document (sources of incoming edges)."""
        if not self._graph.has_node(node_id):
            return []
        results = []
        for pred in self._graph.predecessors(node_id):
            edge_data = self._graph.get_edge_data(pred, node_id) or {}
            source_node = self.get_node(pred)
            results.append({
                "source": pred,
                "relationship": edge_data.get("relationship"),
                "source_node": source_node,
            })
        return results

    def get_policy_lineage(self, node_id_or_identifier: str) -> Dict[str, Any]:
        """Traces the provenance lineage (ancestors and descendants) for a policy node."""
        target_id = node_id_or_identifier
        if not self._graph.has_node(target_id):
            matches = self.find_nodes_by_identifier(node_id_or_identifier)
            if matches:
                target_id = matches[0]["id"]
            else:
                return {"node": None, "predecessors": [], "successors": []}

        return {
            "node": self.get_node(target_id),
            "predecessors": self.get_predecessors(target_id),
            "successors": self.get_successors(target_id),
        }
