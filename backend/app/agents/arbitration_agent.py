"""
Resolution & Arbitration Agent for TruthGuard-Chronos.

Uses LangGraph to arbitrate between conflicting evidence and produce a final,
defensible resolution to a user question.

Arbitration logic (purely deterministic — no LLM calls):
  1. If the Critic gives PASS → accept the draft, outcome = RESOLVED.
  2. If the Critic flags ONLY citation/coverage issues (no conflict) → repair and RESOLVED.
  3. If explicit SUPERSEDES / AMENDS provenance exists for the conflict → apply it, RESOLVED.
  4. If conflicting rules exist but no explicit provenance resolves them → CONFLICT.
  5. If evidence is absent or ABSTAIN from critic → ABSTAIN.

Outcomes:
  RESOLVED  — a defensible final answer exists and is returned.
  CONFLICT  — unresolved contradictions remain; conflicting evidence is surfaced.
  ABSTAIN   — insufficient evidence to produce any answer.
"""

import re
from pathlib import Path
from typing import TypedDict, List, Dict, Any, Optional

from langgraph.graph import StateGraph, START, END

try:
    from app.agents.retriever_chrono_annotator import RetrieverChronoAnnotatorAgent
    from app.agents.synthesizer import SynthesizerAgent
    from app.agents.critic_agent import CriticAgent
    from app.graph.tpcg import TemporalProvenanceConflictGraph, to_json_safe
    from app.graph.conflict_detector import ConflictDetector
except ImportError:
    from retriever_agent import RetrieverChronoAnnotatorAgent
    from synthesizer_agent import SynthesizerAgent
    from critic_agent import CriticAgent
    from tpcg import TemporalProvenanceConflictGraph, to_json_safe
    from conflict_detector import ConflictDetector


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

class ArbitrationState(TypedDict, total=False):
    # Inputs
    question: str
    top_k: int
    filter_files: Optional[List[str]]

    # Retrieval
    retrieved_passages: List[Dict[str, Any]]
    temporal_provenance_metadata: Dict[str, Any]

    # Synthesis
    draft_answer: str
    citations: List[Dict[str, Any]]
    is_sufficiently_supported: bool

    # Critic
    critic_status: str
    critic_issues: List[Dict[str, Any]]
    critic_recommended_action: str

    # Arbitration decision
    outcome: str                    # RESOLVED | CONFLICT | ABSTAIN
    final_answer: str
    explanation: str
    conflicting_evidence: List[Dict[str, Any]]
    abstention_reason: str
    resolution_basis: str           # what rule/provenance resolved the conflict


# ─────────────────────────────────────────────────────────────────────────────
# ArbitrationAgent
# ─────────────────────────────────────────────────────────────────────────────

class ArbitrationAgent:
    """
    LangGraph-based Resolution & Arbitration Agent.

    Integrates Retriever → Synthesizer → Critic → Arbitrator into a 4-node pipeline.
    Never silently resolves conflicts by assuming newest = correct.
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
        self.retriever = RetrieverChronoAnnotatorAgent(tpcg=self.tpcg, upload_dir=self.upload_dir)
        self.synthesizer = SynthesizerAgent(tpcg=self.tpcg, upload_dir=self.upload_dir)
        self.critic = CriticAgent(tpcg=self.tpcg, upload_dir=self.upload_dir)
        self.workflow = self._build_workflow()
        self.app = self.workflow.compile()

    def _build_workflow(self) -> StateGraph:
        wf = StateGraph(ArbitrationState)
        wf.add_node("synthesize", self._synthesize_node)
        wf.add_node("critique", self._critique_node)
        wf.add_node("arbitrate", self._arbitrate_node)
        wf.add_edge(START, "synthesize")
        wf.add_edge("synthesize", "critique")
        wf.add_edge("critique", "arbitrate")
        wf.add_edge("arbitrate", END)
        return wf

    # ── Node 1: synthesize ────────────────────────────────────────────────────

    def _synthesize_node(self, state: ArbitrationState) -> Dict[str, Any]:
        question = state.get("question", "")
        top_k = state.get("top_k", 5)
        filter_files = state.get("filter_files")

        result = self.synthesizer.run(
            question=question,
            top_k=top_k,
            filter_files=filter_files,
        )
        return {
            "draft_answer": result.get("draft_answer", ""),
            "citations": result.get("citations", []),
            "retrieved_passages": result.get("retrieved_evidence", []),
            "temporal_provenance_metadata": result.get("temporal_provenance_metadata", {}),
            "is_sufficiently_supported": result.get("is_sufficiently_supported", False),
        }

    # ── Node 2: critique ──────────────────────────────────────────────────────

    def _critique_node(self, state: ArbitrationState) -> Dict[str, Any]:
        question = state.get("question", "")
        draft = state.get("draft_answer", "")
        top_k = state.get("top_k", 5)
        filter_files = state.get("filter_files")

        result = self.critic.run(
            question=question,
            draft_answer=draft,
            top_k=max(top_k, 10),
            filter_files=filter_files,
        )
        return {
            "critic_status": result.get("critic_status", "ABSTAIN"),
            "critic_issues": result.get("issues", []),
            "critic_recommended_action": result.get("recommended_action", ""),
        }

    # ── Node 3: arbitrate ─────────────────────────────────────────────────────

    def _arbitrate_node(self, state: ArbitrationState) -> Dict[str, Any]:
        critic_status = state.get("critic_status", "ABSTAIN")
        critic_issues = state.get("critic_issues", [])
        draft_answer = state.get("draft_answer", "")
        citations = state.get("citations", [])
        passages = state.get("retrieved_passages", [])
        is_supported = state.get("is_sufficiently_supported", False)

        # ── Case 1: ABSTAIN — no evidence at all ──────────────────────────────
        if critic_status == "ABSTAIN" or not is_supported or not passages:
            return {
                "outcome": "ABSTAIN",
                "final_answer": "",
                "explanation": (
                    "Insufficient evidence was retrieved from the uploaded documents "
                    "to answer this question reliably. No answer is provided."
                ),
                "conflicting_evidence": [],
                "abstention_reason": (
                    state.get("critic_recommended_action") or
                    "No relevant passages found for the question."
                ),
                "resolution_basis": "",
            }

        # Classify critic issues by type
        high_issues = [i for i in critic_issues if i.get("severity") == "HIGH"]
        conflict_issues = [i for i in critic_issues if i.get("issue_type") in (
            "conflicting_rules", "global_vs_regional_scope_mismatch",
        )]
        outdated_issues = [i for i in critic_issues if i.get("issue_type") == "outdated_policy_statement"]
        supersession_issues = [i for i in critic_issues if i.get("issue_type") == "incorrect_supersession_assumption"]
        citation_only_issues = [i for i in critic_issues if i.get("issue_type") in (
            "missing_or_incorrect_citation", "low_evidence_coverage",
        )]

        # ── Case 2: PASS — no significant issues ─────────────────────────────
        if critic_status == "PASS":
            return {
                "outcome": "RESOLVED",
                "final_answer": draft_answer,
                "explanation": (
                    "The draft answer passed all critic checks. "
                    "It is grounded in the retrieved evidence with no unresolved conflicts."
                ),
                "conflicting_evidence": [],
                "abstention_reason": "",
                "resolution_basis": "Critic returned PASS — no adversarial issues identified.",
            }

        # ── Case 3: FLAG but only minor citation / coverage issues ────────────
        if critic_issues and not high_issues and not conflict_issues and not supersession_issues:
            note = ""
            if citation_only_issues:
                note = (
                    "\n\nNote: The critic identified minor citation or coverage issues. "
                    "Key claims should be independently verified against source documents."
                )
            if outdated_issues:
                note += (
                    "\n\nNote: One or more cited passages may be from a superseded document. "
                    "Verify against the most current version before acting."
                )
            return {
                "outcome": "RESOLVED",
                "final_answer": draft_answer + note,
                "explanation": (
                    "The draft answer was accepted with minor qualifications. "
                    "No structural conflicts or unsupported claims were identified."
                ),
                "conflicting_evidence": [],
                "abstention_reason": "",
                "resolution_basis": "Critic raised only minor issues; no conflicts blocked resolution.",
            }

        # ── Case 4: Explicit SUPERSEDES / AMENDS provenance exists ───────────
        superseded_filenames: Dict[str, List[str]] = {}
        superseding_filenames: Dict[str, List[str]] = {}
        for p in passages:
            prov = p.get("provenance", {})
            fname = p.get("metadata", {}).get("filename") or p.get("original_filename", "")
            if prov.get("supersedes"):
                superseding_filenames[fname] = prov["supersedes"]
            if prov.get("is_superseded_warning") and prov.get("superseded_by"):
                superseded_filenames[fname] = prov["superseded_by"]

        # Also check TPCG graph edges directly
        if self.tpcg and self.tpcg.graph:
            for u, v, data in self.tpcg.graph.edges(data=True):
                rel = data.get("relationship", "")
                if rel in ("SUPERSEDES", "AMENDS"):
                    if u not in superseding_filenames:
                        superseding_filenames[u] = []
                    superseding_filenames[u].append(v)

        if (conflict_issues or supersession_issues) and superseding_filenames:
            # Build resolution narrative from explicit provenance
            resolution_parts = []
            for superseder, superseded_list in superseding_filenames.items():
                resolution_parts.append(
                    f"'{superseder}' explicitly supersedes/amends: {', '.join(superseded_list)}."
                )
            resolution_basis = (
                "Resolved using explicit SUPERSEDES/AMENDS relationships in document metadata: "
                + " ".join(resolution_parts)
            )
            # Annotate draft with supersession note
            supersession_note = (
                f"\n\nProvenance Note: {resolution_basis} "
                "This resolution is based on explicit metadata, not on publication date alone."
            )
            return {
                "outcome": "RESOLVED",
                "final_answer": draft_answer + supersession_note,
                "explanation": (
                    "Conflicts were resolved using explicit supersession/amendment provenance "
                    "found in document metadata. The more authoritative document's provisions apply."
                ),
                "conflicting_evidence": [
                    {"issue": i["description"], "evidence": i["evidence"]}
                    for i in conflict_issues + supersession_issues
                ],
                "abstention_reason": "",
                "resolution_basis": resolution_basis,
            }

        # ── Case 5: Unresolved conflict — no explicit provenance to arbitrate ─
        if conflict_issues or (high_issues and not superseding_filenames):
            conflicting_ev = []
            for issue in (conflict_issues + high_issues)[:5]:
                conflicting_ev.append({
                    "issue_type": issue["issue_type"],
                    "description": issue["description"],
                    "evidence": issue["evidence"],
                    "severity": issue["severity"],
                })

            return {
                "outcome": "CONFLICT",
                "final_answer": "",
                "explanation": (
                    "The documents contain conflicting rules or provisions that cannot be resolved "
                    "without explicit supersession, amendment, or authoritative clarification. "
                    "The answer is withheld to avoid presenting misleading information."
                ),
                "conflicting_evidence": conflicting_ev,
                "abstention_reason": "",
                "resolution_basis": (
                    "No explicit SUPERSEDES or AMENDS metadata found to resolve the conflict. "
                    "Human review or authoritative clarification is required."
                ),
            }

        # ── Fallback: flag with qualifications ───────────────────────────────
        return {
            "outcome": "RESOLVED",
            "final_answer": (
                draft_answer +
                "\n\nNote: The critic identified some concerns with this answer. "
                "Please review the source documents before acting on this information."
            ),
            "explanation": "Answer accepted with critic qualifications.",
            "conflicting_evidence": [],
            "abstention_reason": "",
            "resolution_basis": "Critic issues did not rise to CONFLICT threshold.",
        }

    # ── Public run() ─────────────────────────────────────────────────────────

    def run(
        self,
        question: str,
        top_k: int = 5,
        filter_files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        initial_state: ArbitrationState = {
            "question": question,
            "top_k": top_k,
            "filter_files": filter_files,
            "retrieved_passages": [],
            "temporal_provenance_metadata": {},
            "draft_answer": "",
            "citations": [],
            "is_sufficiently_supported": False,
            "critic_status": "ABSTAIN",
            "critic_issues": [],
            "critic_recommended_action": "",
            "outcome": "ABSTAIN",
            "final_answer": "",
            "explanation": "",
            "conflicting_evidence": [],
            "abstention_reason": "",
            "resolution_basis": "",
        }

        final_state = self.app.invoke(initial_state)

        return {
            "question": question,
            "outcome": final_state.get("outcome", "ABSTAIN"),
            "final_answer": final_state.get("final_answer", ""),
            "explanation": final_state.get("explanation", ""),
            "citations": final_state.get("citations", []),
            "conflicting_evidence": final_state.get("conflicting_evidence", []),
            "abstention_reason": final_state.get("abstention_reason", ""),
            "resolution_basis": final_state.get("resolution_basis", ""),
            "draft_answer": final_state.get("draft_answer", ""),
            "critic_status": final_state.get("critic_status", "ABSTAIN"),
            "critic_issues": final_state.get("critic_issues", []),
            "temporal_provenance_metadata": final_state.get("temporal_provenance_metadata", {}),
        }
