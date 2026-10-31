"""
Synthesizer Agent Module for TruthGuard-Chronos.

Uses LangGraph to orchestrate:
  1. Retrieve relevant passages and temporal/provenance metadata via RetrieverChronoAnnotatorAgent.
  2. Evaluate evidence sufficiency and detect temporal relationships between sources.
  3. Synthesize a concise draft answer grounded strictly in the retrieved evidence.
  4. Generate detailed citations for each claim, without assuming a newer document overrides an older one.
"""

import re
from pathlib import Path
from typing import TypedDict, List, Dict, Any, Optional, Set, Tuple
from pydantic import BaseModel, Field

from langgraph.graph import StateGraph, START, END

try:
    from app.agents.retriever_chrono_annotator import RetrieverChronoAnnotatorAgent
    from app.graph.tpcg import TemporalProvenanceConflictGraph, to_json_safe
    from app.gemini_client import get_gemini_client
except ImportError:
    from retriever_agent import RetrieverChronoAnnotatorAgent
    from tpcg import TemporalProvenanceConflictGraph, to_json_safe
    from gemini_client import get_gemini_client


class SynthesizerState(TypedDict, total=False):
    """
    State schema for the LangGraph Synthesizer Agent workflow.
    """
    question: str
    top_k: int
    filter_files: Optional[List[str]]
    retrieved_passages: List[Dict[str, Any]]
    temporal_provenance_metadata: Dict[str, Any]
    citations: List[Dict[str, Any]]
    draft_answer: str
    is_sufficiently_supported: bool
    status: str


def clean_sentence(text: str) -> str:
    """Cleans excess whitespace and linebreaks from sentence."""
    return re.sub(r"\s+", " ", text).strip()


def extract_key_statements(passages: List[Dict[str, Any]], query_words: Set[str]) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Extracts key informative statements from passages matching query concepts.
    Returns list of (clean_sentence, passage_dict).
    """
    key_statements: List[Tuple[str, Dict[str, Any]]] = []
    seen_texts: Set[str] = set()

    for p in passages:
        p_text = p.get("text", "")
        # Break passage into sentences or clean clauses
        sentences = re.split(r"(?<=[.!?])\s+", p_text)
        for s in sentences:
            s_clean = clean_sentence(s)
            # Filter out header-only lines like '19030/1/2017-E.IV' or 'Government of India' unless informative
            if len(s_clean) < 25:
                continue
            s_lower = s_clean.lower()
            # Check if sentence contains query terms or rule directives
            matches_query = any(w in s_lower for w in query_words)
            has_directive = bool(re.search(r"\b(?:allow|allowed|decided|admissible|entitlement|must|shall|required|supersedes|amends|prohibited)\b", s_lower))

            if matches_query or has_directive:
                norm = s_lower[:80]
                if norm not in seen_texts:
                    seen_texts.add(norm)
                    key_statements.append((s_clean, p))

    return key_statements


class SynthesizerAgent:
    """
    LangGraph-based Synthesizer Agent.
    Grounded strictly in retrieved evidence, produces verifiable draft answers with citations.
    """

    def __init__(
        self,
        tpcg: Optional[TemporalProvenanceConflictGraph] = None,
        upload_dir: Optional[Path] = None,
    ):
        self.tpcg = tpcg
        self.upload_dir = upload_dir or (Path(__file__).resolve().parent.parent.parent / "uploads")
        self.retriever_agent = RetrieverChronoAnnotatorAgent(tpcg=self.tpcg, upload_dir=self.upload_dir)
        self.workflow = self._build_langgraph_workflow()
        self.app = self.workflow.compile()

    def _build_langgraph_workflow(self) -> StateGraph:
        """Assembles the LangGraph StateGraph pipeline for synthesis."""
        workflow = StateGraph(SynthesizerState)

        workflow.add_node("retrieve_evidence", self._retrieve_evidence_node)
        workflow.add_node("evaluate_and_synthesize", self._evaluate_and_synthesize_node)

        workflow.add_edge(START, "retrieve_evidence")
        workflow.add_edge("retrieve_evidence", "evaluate_and_synthesize")
        workflow.add_edge("evaluate_and_synthesize", END)

        return workflow

    def _retrieve_evidence_node(self, state: SynthesizerState) -> Dict[str, Any]:
        """
        Step 1: Runs the Retriever & Chrono-Annotator Agent to gather evidence passages.
        """
        question = state.get("question", "")
        top_k = state.get("top_k", 5)
        filter_files = state.get("filter_files")

        retrieval_res = self.retriever_agent.run(
            question=question,
            top_k=top_k,
            filter_files=filter_files,
        )

        return {
            "retrieved_passages": retrieval_res.get("retrieved_passages", []),
            "temporal_provenance_metadata": retrieval_res.get("temporal_provenance_metadata", {}),
        }

    def _evaluate_and_synthesize_node(self, state: SynthesizerState) -> Dict[str, Any]:
        """
        Step 2: Evaluates evidence sufficiency and drafts grounded answer with citations.
        Ensures newer documents are not assumed to override older ones without explicit evidence.
        """
        question = state.get("question", "").strip()
        passages = state.get("retrieved_passages", [])
        temp_meta = state.get("temporal_provenance_metadata", {})

        # Extract meaningful query keywords for grounding evaluation
        raw_words = re.findall(r"\b[A-Za-z0-9_-]+\b", question.lower())
        stopwords = {
            "what", "is", "the", "are", "in", "on", "of", "for", "at", "by", "with", "from",
            "to", "a", "an", "how", "when", "does", "do", "why", "where", "can", "will", "should",
            "you", "your", "if", "not", "i", "me", "my", "we", "our", "it", "its", "they", "them",
        }
        query_words = {w for w in raw_words if w not in stopwords and len(w) >= 3}

        # Meta words that indicate inquiry about evidence rather than a policy domain
        META_WORDS = {
            "question", "questions", "answer", "answers", "document", "documents",
            "uploaded", "evidence", "contain", "contains", "enough", "sufficient",
            "available", "provide", "provided", "reliable", "reliably",
        }
        substantive_query_words = {w for w in query_words if w not in META_WORDS}

        # 1. Check for Insufficient Evidence
        if not passages or not substantive_query_words:
            return {
                "draft_answer": "The available documents do not contain sufficient evidence to support a reliable answer to this question.",
                "citations": [],
                "is_sufficiently_supported": False,
                "status": "insufficient_evidence",
            }

        # Check if any passage actually matched substantive query words
        matched_passages = [
            p for p in passages
            if p.get("relevance_score", 0.0) > 0.5
            and any(w in p.get("matched_terms", []) for w in substantive_query_words)
        ]
        if not matched_passages:
            return {
                "draft_answer": "The available documents do not contain sufficient evidence to support a reliable answer to this question.",
                "citations": [],
                "is_sufficiently_supported": False,
                "status": "insufficient_evidence",
            }

        # 2. Extract Key Claims & Statements from Evidence
        key_statements = extract_key_statements(matched_passages, substantive_query_words)
        if not key_statements:
            return {
                "draft_answer": "The available documents do not contain sufficient evidence to support a reliable answer to this question.",
                "citations": [],
                "is_sufficiently_supported": False,
                "status": "insufficient_evidence",
            }

        citations: List[Dict[str, Any]] = []
        answer_points: List[str] = []
        seen_citation_keys: Dict[str, int] = {}

        # Organize evidence by document to check temporal / supersession context
        docs_involved: Dict[str, Dict[str, Any]] = {}
        for stmt, p in key_statements:
            meta = p.get("metadata", {})
            doc_fname = meta.get("filename") or p.get("original_filename") or "Unknown"
            docs_involved.setdefault(doc_fname, {
                "metadata": meta,
                "provenance": p.get("provenance", {}),
                "statements": [],
            })
            docs_involved[doc_fname]["statements"].append((stmt, p))

        # Check for multiple documents with differing dates or supersession
        has_multiple_docs = len(docs_involved) > 1

        for doc_fname, doc_info in docs_involved.items():
            meta = doc_info["metadata"]
            prov = doc_info["provenance"]
            doc_title = meta.get("document_title") or doc_fname
            doc_ident = meta.get("document_identifier")
            eff_date = meta.get("effective_date") or meta.get("issue_date")
            is_superseded = prov.get("is_superseded_warning", False)
            supersedes = prov.get("supersedes", [])

            # Format doc reference
            doc_ref = f"{doc_title}"
            if doc_ident:
                doc_ref += f" ({doc_ident})"
            if eff_date:
                doc_ref += f", dated {eff_date}"

            for stmt, p in doc_info["statements"][:3]:  # Top informative statements per doc
                p_id = p.get("passage_id")
                # Deduplicate citation by passage_id
                if p_id not in seen_citation_keys:
                    c_num = len(citations) + 1
                    seen_citation_keys[p_id] = c_num
                    citations.append({
                        "citation_id": c_num,
                        "filename": doc_fname,
                        "saved_filename": meta.get("saved_filename"),
                        "document_title": doc_title,
                        "passage_id": p_id,
                        "effective_or_issue_date": eff_date,
                        "document_identifier": doc_ident,
                        "quoted_snippet": stmt,
                    })
                c_idx = seen_citation_keys[p_id]

                # Craft grounded point
                answer_points.append(f"{stmt} [{c_idx}]")

        # 3. Assemble Draft Answer with Strict Grounding and Temporal Integrity
        answer_paragraphs: List[str] = []

        # Intro line referencing sources
        primary_doc_name = list(docs_involved.keys())[0]
        primary_doc_info = docs_involved[primary_doc_name]
        primary_title = primary_doc_info["metadata"].get("document_title") or primary_doc_name
        primary_date = primary_doc_info["metadata"].get("effective_date") or primary_doc_info["metadata"].get("issue_date")
        header_date_str = f" (dated {primary_date})" if primary_date else ""

        answer_paragraphs.append(f"Based on {primary_title}{header_date_str}:")

        for idx, pt in enumerate(answer_points, start=1):
            answer_paragraphs.append(f"• {pt}")

        # Check temporal & conflict guardrails:
        # "Do not treat a newer document as automatically overriding an older one."
        # "Do not resolve conflicts based on assumptions."
        temporal_notes: List[str] = []
        if has_multiple_docs:
            for doc_fname, doc_info in docs_involved.items():
                prov = doc_info["provenance"]
                if prov.get("supersedes"):
                    superseded_targets = ", ".join(prov["supersedes"])
                    temporal_notes.append(
                        f"Document '{doc_fname}' contains an explicit supersession clause stating that it supersedes {superseded_targets}."
                    )
                elif prov.get("is_superseded_warning"):
                    superseding_sources = ", ".join(prov.get("superseded_by", []))
                    temporal_notes.append(
                        f"Provisions from '{doc_fname}' are superseded by {superseding_sources}."
                    )

            if temporal_notes:
                answer_paragraphs.append("\nTemporal & Provenance Note:")
                for note in temporal_notes:
                    answer_paragraphs.append(f"- {note}")
            else:
                answer_paragraphs.append(
                    "\nTemporal Note: Multiple relevant documents were consulted across different dates. "
                    "Under TruthGuard rules, newer publication dates are not treated as automatically overriding older provisions "
                    "without explicit supersession or amendment metadata."
                )

        rule_based_draft_answer = "\n".join(answer_paragraphs)

        # 4. Integrate Gemini API for natural, grounded synthesis when available
        gemini = get_gemini_client()
        final_draft_answer = None

        if gemini.is_available:
            final_draft_answer = gemini.synthesize_grounded_answer(
                question=question,
                evidence_passages=matched_passages,
                citations=citations,
                temporal_notes=temporal_notes if has_multiple_docs else None,
            )

        # Fallback to deterministic rule-based output if Gemini is unconfigured or fails
        if not final_draft_answer:
            final_draft_answer = rule_based_draft_answer

        return {
            "draft_answer": final_draft_answer,
            "citations": citations,
            "is_sufficiently_supported": True,
            "status": "supported",
        }

    def run(self, question: str, top_k: int = 5, filter_files: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Runs the Synthesizer Agent workflow end-to-end and returns structured results.
        """
        initial_state: SynthesizerState = {
            "question": question,
            "top_k": top_k,
            "filter_files": filter_files,
            "retrieved_passages": [],
            "temporal_provenance_metadata": {},
            "citations": [],
            "draft_answer": "",
            "is_sufficiently_supported": False,
            "status": "initialized",
        }

        final_state = self.app.invoke(initial_state)

        return {
            "question": final_state.get("question", question),
            "draft_answer": final_state.get("draft_answer", ""),
            "citations": final_state.get("citations", []),
            "retrieved_evidence": final_state.get("retrieved_passages", []),
            "is_sufficiently_supported": final_state.get("is_sufficiently_supported", False),
            "temporal_provenance_metadata": final_state.get("temporal_provenance_metadata", {}),
        }
