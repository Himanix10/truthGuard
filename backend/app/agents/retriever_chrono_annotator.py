"""
Retriever & Chrono-Annotator Agent Module for TruthGuard-Chronos.

Uses LangGraph to orchestrate a multi-step agent workflow:
  1. analyze_query: Extracts query terms, entity references, and temporal filters.
  2. retrieve_passages: Performs keyword matching / TF-IDF relevance scoring on passages.
  3. chrono_annotate: Annotates retrieved passages with temporal, metadata, and provenance attributes.
"""

import re
import math
from pathlib import Path
from typing import TypedDict, List, Dict, Any, Optional, Set, Union
from pydantic import BaseModel, Field

from langgraph.graph import StateGraph, START, END

try:
    from app.graph.tpcg import (
        TemporalProvenanceConflictGraph,
        extract_text_from_file,
        get_original_filename,
        parse_date_for_comparison,
        to_json_safe,
    )
    from app.ingestion.metadata_extractor import extract_document_metadata, DocumentMetadata
except ImportError:
    from tpcg import (
        TemporalProvenanceConflictGraph,
        extract_text_from_file,
        get_original_filename,
        parse_date_for_comparison,
        to_json_safe,
    )
    from metadata_extractor import extract_document_metadata, DocumentMetadata


# Standard English stopwords to filter during query tokenization
STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but",
    "by", "can", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just",
    "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once",
    "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "s", "same", "she",
    "should", "so", "some", "such", "t", "than", "that", "the", "their", "theirs", "them",
    "themselves", "then", "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "would", "you", "your", "yours", "yourself",
}


class RetrieverAnnotatorState(TypedDict, total=False):
    """
    State schema for the LangGraph Retriever & Chrono-Annotator Agent workflow.
    """
    question: str
    top_k: int
    filter_files: Optional[List[str]]
    query_terms: List[str]
    raw_passages: List[Dict[str, Any]]
    retrieved_passages: List[Dict[str, Any]]
    temporal_provenance_metadata: Dict[str, Any]
    error: Optional[str]


def split_text_into_passages(text: str, saved_filename: str, original_filename: str, doc_metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Splits document text into citation-friendly contextual passages (paragraphs or multi-sentence blocks).
    Ensures passages are long enough to provide useful context for citation.
    """
    if not text or not text.strip():
        return []

    raw_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    passages: List[Dict[str, Any]] = []
    p_idx = 0

    for para in raw_paragraphs:
        # If paragraph is short, or standard length (60 - 600 chars), keep as single passage
        if len(para) <= 600:
            passages.append({
                "passage_id": f"{saved_filename}_p{p_idx}",
                "text": para,
                "saved_filename": saved_filename,
                "original_filename": original_filename,
                "metadata": doc_metadata,
            })
            p_idx += 1
        else:
            # For longer paragraphs, break into sentence chunks of ~300 chars with overlap
            sentences = re.split(r"(?<=[.!?])\s+", para)
            current_chunk: List[str] = []
            current_len = 0

            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                current_chunk.append(sent)
                current_len += len(sent) + 1

                if current_len >= 300:
                    chunk_text = " ".join(current_chunk)
                    passages.append({
                        "passage_id": f"{saved_filename}_p{p_idx}",
                        "text": chunk_text,
                        "saved_filename": saved_filename,
                        "original_filename": original_filename,
                        "metadata": doc_metadata,
                    })
                    p_idx += 1
                    # Keep last sentence as overlap for context continuity
                    current_chunk = [current_chunk[-1]] if len(current_chunk) > 1 else []
                    current_len = sum(len(s) + 1 for s in current_chunk)

            if current_chunk:
                chunk_text = " ".join(current_chunk)
                passages.append({
                    "passage_id": f"{saved_filename}_p{p_idx}",
                    "text": chunk_text,
                    "saved_filename": saved_filename,
                    "original_filename": original_filename,
                    "metadata": doc_metadata,
                })
                p_idx += 1

    return passages


def compute_tfidf_scores(passages: List[Dict[str, Any]], query_terms: List[str], raw_query: str) -> List[Dict[str, Any]]:
    """
    Calculates TF-IDF relevance scores between query terms and passages.
    Adds scoring bonuses for exact phrase match and identifier matches.
    """
    if not passages or not query_terms:
        return []

    total_passages = len(passages)

    # 1. Compute document frequency for each query term
    doc_freq: Dict[str, int] = {term: 0 for term in query_terms}
    for p in passages:
        p_text_lower = p["text"].lower()
        for term in query_terms:
            if re.search(r"\b" + re.escape(term) + r"\b", p_text_lower):
                doc_freq[term] += 1

    # 2. Compute IDF for each query term
    idf: Dict[str, float] = {}
    for term, df in doc_freq.items():
        # Standard smoothed BM25/TF-IDF formula
        idf[term] = math.log(1.0 + (total_passages - df + 0.5) / (df + 0.5)) + 1.0

    scored_passages: List[Dict[str, Any]] = []
    clean_query = raw_query.strip().lower()

    for p in passages:
        p_text = p["text"]
        p_lower = p_text.lower()
        words = re.findall(r"\w+", p_lower)
        num_words = len(words) or 1

        score = 0.0
        matched_terms: List[str] = []

        for term in query_terms:
            count = len(re.findall(r"\b" + re.escape(term) + r"\b", p_lower))
            if count > 0:
                tf = count / num_words
                score += tf * idf[term] * 10.0
                matched_terms.append(term)

        # Bonus 1: Exact phrase match
        if len(clean_query) > 5 and clean_query in p_lower:
            score += 5.0

        # Bonus 2: Document title / identifier match in passage metadata
        meta = p.get("metadata", {})
        doc_id = (meta.get("document_identifier") or meta.get("policy_or_document_identifier") or "").lower()
        title = (meta.get("title") or meta.get("document_title") or "").lower()
        for term in query_terms:
            if doc_id and term in doc_id:
                score += 3.0
            if title and term in title:
                score += 1.5

        if score > 0.0 and matched_terms:
            scored_p = dict(p)
            scored_p["relevance_score"] = score
            scored_p["matched_terms"] = matched_terms
            scored_passages.append(scored_p)

    # Sort descending by relevance score
    scored_passages.sort(key=lambda x: x["relevance_score"], reverse=True)
    return scored_passages


class RetrieverChronoAnnotatorAgent:
    """
    LangGraph Agent responsible for retrieving relevant contextual passages from
    uploaded documents and annotating them with temporal and provenance metadata.
    """

    def __init__(
        self,
        tpcg: Optional[TemporalProvenanceConflictGraph] = None,
        upload_dir: Optional[Path] = None,
    ):
        self.upload_dir = upload_dir or (Path(__file__).resolve().parent.parent.parent / "uploads")
        if tpcg is None:
            self.tpcg = TemporalProvenanceConflictGraph()
            self.tpcg.build_from_directory(self.upload_dir)
        else:
            self.tpcg = tpcg
        self.workflow = self._build_langgraph_workflow()
        self.app = self.workflow.compile()

    def _build_langgraph_workflow(self) -> StateGraph:
        """Assembles the LangGraph StateGraph pipeline."""
        workflow = StateGraph(RetrieverAnnotatorState)

        workflow.add_node("analyze_query", self._analyze_query_node)
        workflow.add_node("retrieve_passages", self._retrieve_passages_node)
        workflow.add_node("chrono_annotate", self._chrono_annotate_node)

        workflow.add_edge(START, "analyze_query")
        workflow.add_edge("analyze_query", "retrieve_passages")
        workflow.add_edge("retrieve_passages", "chrono_annotate")
        workflow.add_edge("chrono_annotate", END)

        return workflow

    def _analyze_query_node(self, state: RetrieverAnnotatorState) -> Dict[str, Any]:
        """
        Step 1: Analyzes user question and extracts search keywords.
        """
        question = state.get("question", "")
        if not question or not question.strip():
            return {"query_terms": []}

        # Tokenize query into alphanumeric words
        raw_words = re.findall(r"\b[A-Za-z0-9_-]+\b", question.lower())
        query_terms = [w for w in raw_words if w not in STOPWORDS and len(w) >= 2]

        # If all words were stopwords, fallback to all words with len >= 2
        if not query_terms:
            query_terms = [w for w in raw_words if len(w) >= 2]

        return {"query_terms": query_terms}

    def _retrieve_passages_node(self, state: RetrieverAnnotatorState) -> Dict[str, Any]:
        """
        Step 2: Collects uploaded document passages and scores them using TF-IDF.
        """
        query_terms = state.get("query_terms", [])
        question = state.get("question", "")
        top_k = state.get("top_k", 5)
        filter_files = state.get("filter_files")

        clean_filters = {f.strip().upper() for f in filter_files} if filter_files else None

        # Gather documents from TPCG graph or directory
        all_passages: List[Dict[str, Any]] = []

        if self.tpcg and self.tpcg.node_count > 0:
            for node_id in self.tpcg.graph.nodes:
                data = self.tpcg.graph.nodes[node_id]
                orig_name = data.get("original_filename") or data.get("filename") or node_id
                saved_name = data.get("saved_filename") or node_id

                if clean_filters:
                    if (
                        node_id.upper() not in clean_filters
                        and orig_name.upper() not in clean_filters
                        and saved_name.upper() not in clean_filters
                    ):
                        continue

                text = data.get("raw_text")
                if not text:
                    file_p = self.upload_dir / saved_name
                    if file_p.exists():
                        text = extract_text_from_file(file_p)

                doc_meta = {
                    "filename": orig_name,
                    "saved_filename": saved_name,
                    "document_title": data.get("title") or data.get("document_title"),
                    "effective_date": data.get("effective_date"),
                    "issue_date": data.get("issue_date") or data.get("publication_or_issue_date"),
                    "version": data.get("version") or data.get("version_number"),
                    "scope": data.get("scope") or data.get("geographic_or_organizational_scope"),
                    "document_identifier": data.get("document_identifier") or data.get("policy_or_document_identifier"),
                    "amendment_status": data.get("amendment_status", False),
                    "parent_policy_identifier": data.get("parent_policy_identifier"),
                }

                passages = split_text_into_passages(text or "", saved_name, orig_name, doc_meta)
                all_passages.extend(passages)
        else:
            # Fallback directly to files in UPLOAD_DIR
            allowed_exts = {".pdf", ".txt"}
            for f_path in sorted(self.upload_dir.iterdir()):
                if not f_path.is_file() or f_path.name.startswith(".") or f_path.suffix.lower() not in allowed_exts:
                    continue
                orig_name = get_original_filename(f_path.name)
                saved_name = f_path.name

                if clean_filters:
                    if orig_name.upper() not in clean_filters and saved_name.upper() not in clean_filters:
                        continue

                text = extract_text_from_file(f_path)
                meta_obj = extract_document_metadata(text, orig_name)
                meta_dict = meta_obj.model_dump()
                doc_meta = {
                    "filename": orig_name,
                    "saved_filename": saved_name,
                    "document_title": meta_dict.get("document_title"),
                    "effective_date": meta_dict.get("effective_date"),
                    "issue_date": meta_dict.get("publication_or_issue_date"),
                    "version": meta_dict.get("version_number"),
                    "scope": meta_dict.get("geographic_or_organizational_scope"),
                    "document_identifier": meta_dict.get("policy_or_document_identifier"),
                    "amendment_status": meta_dict.get("appears_amendment_or_replacement", False),
                    "parent_policy_identifier": meta_dict.get("referenced_parent_or_previous_policy_identifier"),
                }

                passages = split_text_into_passages(text, saved_name, orig_name, doc_meta)
                all_passages.extend(passages)

        # Score passages with TF-IDF
        scored = compute_tfidf_scores(all_passages, query_terms, question)
        selected = scored[:top_k]

        return {
            "raw_passages": all_passages,
            "retrieved_passages": selected,
        }

    def _chrono_annotate_node(self, state: RetrieverAnnotatorState) -> Dict[str, Any]:
        """
        Step 3: Annotates retrieved passages with complete temporal and provenance metadata.
        """
        passages = state.get("retrieved_passages", [])
        annotated: List[Dict[str, Any]] = []

        distinct_docs: Set[str] = set()
        earliest_date = None
        latest_date = None
        doc_identifiers: Set[str] = set()
        contains_superseded = False

        for p in passages:
            meta = p.get("metadata", {})
            saved_name = p.get("saved_filename") or meta.get("saved_filename")
            orig_name = p.get("original_filename") or meta.get("filename")

            distinct_docs.add(orig_name)

            # Dates
            eff_date = meta.get("effective_date")
            iss_date = meta.get("issue_date")
            doc_id = meta.get("document_identifier")
            if doc_id:
                doc_identifiers.add(doc_id)

            for d_str in (eff_date, iss_date):
                parsed = parse_date_for_comparison(d_str)
                if parsed:
                    if earliest_date is None or parsed < earliest_date:
                        earliest_date = parsed
                    if latest_date is None or parsed > latest_date:
                        latest_date = parsed

            # Look up provenance in TPCG graph if available
            supersedes_list: List[str] = []
            superseded_by_list: List[str] = []
            amends_list: List[str] = []

            if self.tpcg and saved_name and self.tpcg.graph.has_node(saved_name):
                # Outgoing edges from this document
                for succ in self.tpcg.graph.successors(saved_name):
                    e_data = self.tpcg.graph.get_edge_data(saved_name, succ) or {}
                    rel = e_data.get("relationship")
                    target_data = self.tpcg.graph.nodes.get(succ, {})
                    target_ident = target_data.get("document_identifier") or target_data.get("original_filename") or succ
                    if rel == "SUPERSEDES":
                        supersedes_list.append(target_ident)
                    elif rel == "AMENDS":
                        amends_list.append(target_ident)

                # Incoming edges to this document (checks if this document is superseded by something newer)
                for pred in self.tpcg.graph.predecessors(saved_name):
                    e_data = self.tpcg.graph.get_edge_data(pred, saved_name) or {}
                    rel = e_data.get("relationship")
                    source_data = self.tpcg.graph.nodes.get(pred, {})
                    source_ident = source_data.get("document_identifier") or source_data.get("original_filename") or pred
                    if rel == "SUPERSEDES":
                        superseded_by_list.append(source_ident)
                        contains_superseded = True

            annotated.append({
                "passage_id": p.get("passage_id"),
                "text": p.get("text"),
                "relevance_score": round(float(p.get("relevance_score", 0.0)), 4),
                "matched_terms": p.get("matched_terms", []),
                "metadata": {
                    "filename": orig_name,
                    "saved_filename": saved_name,
                    "document_title": meta.get("document_title"),
                    "effective_date": eff_date,
                    "issue_date": iss_date,
                    "version": meta.get("version"),
                    "scope": meta.get("scope"),
                    "document_identifier": doc_id,
                },
                "provenance": {
                    "amendment_status": meta.get("amendment_status", False),
                    "parent_policy_identifier": meta.get("parent_policy_identifier"),
                    "supersedes": supersedes_list,
                    "superseded_by": superseded_by_list,
                    "amends": amends_list,
                    "is_superseded_warning": bool(superseded_by_list),
                },
            })

        temporal_provenance_metadata = {
            "documents_consulted": len(distinct_docs),
            "total_passages_evaluated": len(state.get("raw_passages", [])),
            "earliest_effective_date": earliest_date.isoformat() if earliest_date else None,
            "latest_effective_date": latest_date.isoformat() if latest_date else None,
            "relevant_document_identifiers": sorted(list(doc_identifiers)),
            "contains_superseded_passages": contains_superseded,
        }

        return {
            "retrieved_passages": annotated,
            "temporal_provenance_metadata": temporal_provenance_metadata,
        }

    def run(self, question: str, top_k: int = 5, filter_files: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Executes the LangGraph agent workflow end-to-end and returns structured results.
        """
        initial_state: RetrieverAnnotatorState = {
            "question": question,
            "top_k": top_k,
            "filter_files": filter_files,
            "query_terms": [],
            "raw_passages": [],
            "retrieved_passages": [],
            "temporal_provenance_metadata": {},
        }

        final_state = self.app.invoke(initial_state)

        return {
            "question": final_state.get("question", question),
            "passages_count": len(final_state.get("retrieved_passages", [])),
            "retrieved_passages": final_state.get("retrieved_passages", []),
            "temporal_provenance_metadata": final_state.get("temporal_provenance_metadata", {}),
        }

