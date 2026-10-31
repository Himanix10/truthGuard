"""
Main End-to-End Orchestration Workflow for TruthGuard-Chronos.

LangGraph pipeline integrating:
  Retriever & Chrono-Annotator → Synthesizer → Critic → Arbitrator

Accepts a user question and returns a final, auditable outcome.
"""

from pathlib import Path
from typing import TypedDict, List, Dict, Any, Optional

from langgraph.graph import StateGraph, START, END

try:
    from app.agents.arbitration_agent import ArbitrationAgent
    from app.graph.tpcg import TemporalProvenanceConflictGraph
except ImportError:
    from arbitration_agent import ArbitrationAgent
    from tpcg import TemporalProvenanceConflictGraph


class OrchestratorState(TypedDict, total=False):
    question: str
    top_k: int
    filter_files: Optional[List[str]]
    outcome: str
    final_answer: str
    explanation: str
    citations: List[Dict[str, Any]]
    conflicting_evidence: List[Dict[str, Any]]
    abstention_reason: str
    resolution_basis: str
    draft_answer: str
    critic_status: str
    critic_issues: List[Dict[str, Any]]
    temporal_provenance_metadata: Dict[str, Any]


class OrchestratorWorkflow:
    """
    Top-level TruthGuard orchestration workflow.
    Delegates to ArbitrationAgent which internally chains:
    Retriever → Synthesizer → Critic → Arbitrator.
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
        self.arbitration_agent = ArbitrationAgent(tpcg=self.tpcg, upload_dir=self.upload_dir)
        self.workflow = self._build_workflow()
        self.app = self.workflow.compile()

    def _build_workflow(self) -> StateGraph:
        wf = StateGraph(OrchestratorState)
        wf.add_node("run_pipeline", self._run_pipeline_node)
        wf.add_edge(START, "run_pipeline")
        wf.add_edge("run_pipeline", END)
        return wf

    def _run_pipeline_node(self, state: OrchestratorState) -> Dict[str, Any]:
        result = self.arbitration_agent.run(
            question=state.get("question", ""),
            top_k=state.get("top_k", 5),
            filter_files=state.get("filter_files"),
        )
        return {k: v for k, v in result.items() if k != "question"}

    def run(
        self,
        question: str,
        top_k: int = 5,
        filter_files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        initial: OrchestratorState = {
            "question": question,
            "top_k": top_k,
            "filter_files": filter_files,
        }
        final = self.app.invoke(initial)
        return {
            "question": question,
            "outcome": final.get("outcome", "ABSTAIN"),
            "final_answer": final.get("final_answer", ""),
            "explanation": final.get("explanation", ""),
            "citations": final.get("citations", []),
            "conflicting_evidence": final.get("conflicting_evidence", []),
            "abstention_reason": final.get("abstention_reason", ""),
            "resolution_basis": final.get("resolution_basis", ""),
            "draft_answer": final.get("draft_answer", ""),
            "critic_status": final.get("critic_status", "ABSTAIN"),
            "critic_issues": final.get("critic_issues", []),
            "temporal_provenance_metadata": final.get("temporal_provenance_metadata", {}),
        }
