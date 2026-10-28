from typing import TypedDict, List, Dict, Any, Optional


class VerificationState(TypedDict):
    """
    State schema tracking the verification workflow in LangGraph.
    """
    claim: str
    temporal_context: Optional[str]
    retrieved_documents: List[Dict[str, Any]]
    extracted_timeline: List[Dict[str, Any]]
    cross_examination_notes: List[str]
    verdict: Optional[str]
    confidence_score: float
    final_report: Optional[str]

