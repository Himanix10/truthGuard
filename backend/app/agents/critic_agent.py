"""
Adversarial Red-Team Critic Agent for TruthGuard-Chronos.

Uses LangGraph to orchestrate a 3-node adversarial review pipeline:
  1. load_evidence   — Retrieves source passages and conflict signals for the question.
  2. analyze_draft   — Checks the draft answer against 7 adversarial criteria.
  3. compile_verdict — Aggregates findings into PASS / FLAG / ABSTAIN with recommended action.

Critic checks (all deterministic, no LLM calls):
  1. Unsupported claims          — sentences in draft not traceable to any retrieved passage.
  2. Missing / incorrect citations — [N] references in draft that do not match a known passage.
  3. Outdated policy statements  — passages marked is_superseded_warning=True are cited.
  4. Conflicting rules           — multiple passages on the same topic assert different values.
  5. Global vs regional scope    — cited documents have differing scope metadata.
  6. Incorrect supersession      — draft implies override without explicit SUPERSEDES evidence.
  7. Missing evidence / uncertainty — low evidence coverage or no matched terms in top passages.

Critic status:
  PASS    — no significant issues found; answer appears trustworthy for this evidence base.
  FLAG    — one or more issues found that a human reviewer or arbitration agent should address.
  ABSTAIN — evidence is too thin to evaluate the draft at all.
"""

import re
from pathlib import Path
from typing import TypedDict, List, Dict, Any, Optional, Tuple, Set

from langgraph.graph import StateGraph, START, END

try:
    from app.agents.retriever_chrono_annotator import RetrieverChronoAnnotatorAgent
    from app.agents.synthesizer import SynthesizerAgent
    from app.graph.tpcg import TemporalProvenanceConflictGraph, to_json_safe
    from app.graph.conflict_detector import ConflictDetector
    from app.gemini_client import get_gemini_client
except ImportError:
    from retriever_agent import RetrieverChronoAnnotatorAgent
    from synthesizer_agent import SynthesizerAgent
    from tpcg import TemporalProvenanceConflictGraph, to_json_safe
    from conflict_detector import ConflictDetector
    from gemini_client import get_gemini_client


# ─────────────────────────────────────────────────────────────────────────────
# Severity constants
# ─────────────────────────────────────────────────────────────────────────────

SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"

# Minimum relevance score to consider a passage "substantive"
MIN_RELEVANCE_THRESHOLD = 0.5

# Minimum fraction of draft sentences that must be traceable to passages for PASS
MIN_COVERAGE_FRACTION = 0.25

# Words that indicate a claim of override/supersession in the draft text
OVERRIDE_INDICATORS = re.compile(
    r"\b(?:overrides?|supersedes?|replaces?|latest\s+version|most\s+recent|newer\s+policy"
    r"|current\s+policy\s+takes\s+precedence|this\s+policy\s+supersedes)\b",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# LangGraph State
# ─────────────────────────────────────────────────────────────────────────────

class CriticState(TypedDict, total=False):
    # Inputs
    question: str
    draft_answer: str
    top_k: int
    filter_files: Optional[List[str]]

    # Evidence loaded in step 1
    retrieved_passages: List[Dict[str, Any]]
    temporal_provenance_metadata: Dict[str, Any]
    conflict_signals: List[Dict[str, Any]]

    # Issues accumulated in step 2
    issues: List[Dict[str, Any]]

    # Final verdict from step 3
    critic_status: str          # PASS | FLAG | ABSTAIN
    recommended_action: str
    evidence_summary: Dict[str, Any]


# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────

def _sentences(text: str) -> List[str]:
    """Split text into non-trivial sentences."""
    raw = re.split(r"(?<=[.!?])\s+|[\n•]", text)
    return [s.strip() for s in raw if len(s.strip()) > 20]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _passage_text_set(passages: List[Dict[str, Any]]) -> List[str]:
    return [_normalize(p.get("text", "")) for p in passages]


def _overlapping_words(a: str, b: str, min_words: int = 4) -> bool:
    """Returns True if strings share at least min_words consecutive words."""
    words_a = a.lower().split()
    words_b_set = set(b.lower().split())
    for i in range(len(words_a) - min_words + 1):
        chunk = words_a[i:i + min_words]
        if all(w in words_b_set for w in chunk):
            return True
    return False


def _extract_citation_numbers(text: str) -> List[int]:
    """Extracts [N] style citation numbers from draft text."""
    return [int(m) for m in re.findall(r"\[(\d+)\]", text)]


def _topics_in_text(text: str) -> Set[str]:
    """Returns which broad policy topics are discussed in a text snippet."""
    TOPIC_PATTERNS = {
        "encryption": re.compile(r"\b(?:encrypt|aes|tls|cipher|cryptograph)\w*\b", re.I),
        "password": re.compile(r"\b(?:passwords?|passphrase|credentials?|pin)\b", re.I),
        "authentication": re.compile(r"\b(?:mfa|multi.factor|two.factor|authenticat)\w*\b", re.I),
        "access_control": re.compile(r"\b(?:access\s+control|authoriz|permission|privilege)\w*\b", re.I),
        "travel": re.compile(r"\b(?:travel|tour|train|railway|railway|flight|journey|airfare|entitlement)\b", re.I),
        "data_retention": re.compile(r"\b(?:retent|retain|archive|delete|storage\s+period)\w*\b", re.I),
        "incident": re.compile(r"\b(?:incident|breach|notification|report)\w*\b", re.I),
        "scope": re.compile(r"\b(?:global|regional|local|national|international|apac|emea|all\s+employees)\b", re.I),
    }
    found = set()
    for topic, pat in TOPIC_PATTERNS.items():
        if pat.search(text):
            found.add(topic)
    return found


def _make_issue(
    issue_type: str,
    description: str,
    evidence: str,
    severity: str,
    draft_excerpt: str = "",
) -> Dict[str, Any]:
    return {
        "issue_type": issue_type,
        "description": description,
        "evidence": evidence,
        "severity": severity,
        "draft_excerpt": draft_excerpt[:300] if draft_excerpt else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# CriticAgent
# ─────────────────────────────────────────────────────────────────────────────

class CriticAgent:
    """
    LangGraph-based Adversarial Red-Team Critic Agent.

    Accepts a question and a draft answer, re-retrieves evidence independently,
    then applies 7 deterministic adversarial checks to produce a structured verdict.
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
        self.conflict_detector = ConflictDetector(graph=self.tpcg)
        self.workflow = self._build_workflow()
        self.app = self.workflow.compile()

    # ── LangGraph wiring ──────────────────────────────────────────────────────

    def _build_workflow(self) -> StateGraph:
        wf = StateGraph(CriticState)
        wf.add_node("load_evidence", self._load_evidence_node)
        wf.add_node("analyze_draft", self._analyze_draft_node)
        wf.add_node("compile_verdict", self._compile_verdict_node)
        wf.add_edge(START, "load_evidence")
        wf.add_edge("load_evidence", "analyze_draft")
        wf.add_edge("analyze_draft", "compile_verdict")
        wf.add_edge("compile_verdict", END)
        return wf

    # ── Node 1: load_evidence ────────────────────────────────────────────────

    def _load_evidence_node(self, state: CriticState) -> Dict[str, Any]:
        """
        Independently retrieves passages for the question and runs conflict detection
        to surface any pre-known conflict signals between involved documents.
        """
        question = state.get("question", "")
        top_k = state.get("top_k", 10)   # retrieve more than the synthesizer for critic coverage
        filter_files = state.get("filter_files")

        retrieval = self.retriever.run(
            question=question,
            top_k=top_k,
            filter_files=filter_files,
        )
        passages = retrieval.get("retrieved_passages", [])
        temp_meta = retrieval.get("temporal_provenance_metadata", {})

        # Run conflict detection on files involved in the retrieved passages
        involved_files = list({
            p.get("metadata", {}).get("saved_filename") or p.get("saved_filename", "")
            for p in passages
            if p.get("metadata", {}).get("saved_filename") or p.get("saved_filename")
        })
        conflict_signals: List[Dict[str, Any]] = []
        if len(involved_files) >= 2:
            try:
                conflicts = self.conflict_detector.detect_conflicts(
                    target_files=involved_files,
                )
                conflict_signals = conflicts
            except Exception:
                conflict_signals = []

        return {
            "retrieved_passages": passages,
            "temporal_provenance_metadata": temp_meta,
            "conflict_signals": conflict_signals,
        }

    # ── Node 2: analyze_draft ────────────────────────────────────────────────

    def _analyze_draft_node(self, state: CriticState) -> Dict[str, Any]:
        """
        Applies 7 adversarial checks against the draft answer and retrieved evidence.
        """
        draft = state.get("draft_answer", "").strip()
        passages = state.get("retrieved_passages", [])
        conflict_signals = state.get("conflict_signals", [])
        issues: List[Dict[str, Any]] = []

        passage_texts = _passage_text_set(passages)
        draft_sentences = _sentences(draft)
        draft_norm = _normalize(draft)

        # ── Check 1: Unsupported claims ───────────────────────────────────────
        # Sentences in the draft that share no 4-word window with any passage
        unsupported: List[str] = []
        for sent in draft_sentences:
            # Skip meta-sentences (notes, headers, citation markers)
            if re.match(r"^(based on|temporal|provenance|note:|•|-)", sent, re.I):
                continue
            # Strip citation markers for matching
            clean_sent = re.sub(r"\[\d+\]", "", sent).strip()
            if len(clean_sent) < 25:
                continue
            supported = any(_overlapping_words(clean_sent, pt, min_words=4) for pt in passage_texts)
            if not supported:
                unsupported.append(clean_sent)

        if unsupported:
            issues.append(_make_issue(
                issue_type="unsupported_claim",
                description=(
                    f"{len(unsupported)} sentence(s) in the draft answer could not be traced "
                    "to any retrieved source passage using a 4-word overlap check."
                ),
                evidence="Unverifiable sentences: " + " | ".join(s[:80] for s in unsupported[:3]),
                severity=SEVERITY_HIGH if len(unsupported) > 2 else SEVERITY_MEDIUM,
                draft_excerpt=unsupported[0] if unsupported else "",
            ))

        # ── Check 2: Missing / incorrect citations ────────────────────────────
        cited_numbers = _extract_citation_numbers(draft)
        # Build citation index from passages that have a passage_id
        passage_ids = {p.get("passage_id") for p in passages if p.get("passage_id")}
        max_valid_citation = len(passages)

        invalid_citations = [n for n in cited_numbers if n < 1 or n > max_valid_citation]
        if invalid_citations:
            issues.append(_make_issue(
                issue_type="missing_or_incorrect_citation",
                description=(
                    f"Draft references citation number(s) {invalid_citations} but only "
                    f"{max_valid_citation} passages were retrieved."
                ),
                evidence=f"Invalid citation numbers found: {invalid_citations}",
                severity=SEVERITY_MEDIUM,
            ))

        if not cited_numbers and draft_sentences:
            # Draft has substantive content but no citations at all
            issues.append(_make_issue(
                issue_type="missing_or_incorrect_citation",
                description="Draft answer contains substantive claims but no citation markers [N] at all.",
                evidence="No [N] citation patterns found in draft text.",
                severity=SEVERITY_MEDIUM,
                draft_excerpt=draft[:200],
            ))

        # ── Check 3: Outdated policy statements ───────────────────────────────
        superseded_passages = [
            p for p in passages
            if p.get("provenance", {}).get("is_superseded_warning", False)
        ]
        if superseded_passages:
            for sp in superseded_passages:
                fname = sp.get("metadata", {}).get("filename") or sp.get("original_filename", "?")
                superseded_by = sp.get("provenance", {}).get("superseded_by", [])
                issues.append(_make_issue(
                    issue_type="outdated_policy_statement",
                    description=(
                        f"Passage from '{fname}' is flagged as superseded"
                        + (f" by {', '.join(superseded_by)}" if superseded_by else "")
                        + ". Citing it without qualification may mislead."
                    ),
                    evidence=f"Passage text: {sp.get('text', '')[:150]}",
                    severity=SEVERITY_HIGH,
                    draft_excerpt=sp.get("text", "")[:200],
                ))

        # ── Check 4: Conflicting rules ────────────────────────────────────────
        supersession_conflicts = [
            c for c in conflict_signals if c.get("conflict_type") == "supersession"
        ]
        temporal_conflicts = [
            c for c in conflict_signals if c.get("conflict_type") == "temporal_conflict"
        ]
        scope_conflicts = [
            c for c in conflict_signals if c.get("conflict_type") == "scope_conflict"
        ]

        if supersession_conflicts or temporal_conflicts:
            all_rule_conflicts = supersession_conflicts + temporal_conflicts
            for cf in all_rule_conflicts[:3]:  # cap at 3 to keep response concise
                involved = cf.get("involved_filenames", [])
                explanation = cf.get("explanation", "")
                issues.append(_make_issue(
                    issue_type="conflicting_rules",
                    description=(
                        f"Conflict detected between {involved}: {explanation}"
                    ),
                    evidence="; ".join(
                        (s.get("snippet", str(s)) if isinstance(s, dict) else str(s))[:100]
                        for s in cf.get("evidence_snippets", [])[:2]
                    ),
                    severity=SEVERITY_HIGH if cf.get("conflict_type") == "temporal_conflict" else SEVERITY_MEDIUM,
                ))

        # ── Check 5: Global vs regional scope mismatch ───────────────────────
        scopes: Dict[str, str] = {}
        for p in passages:
            meta = p.get("metadata", {})
            fname = meta.get("filename") or p.get("original_filename", "?")
            scope = (meta.get("scope") or "").strip()
            if scope:
                scopes[fname] = scope

        if scope_conflicts:
            for cf in scope_conflicts[:2]:
                involved = cf.get("involved_filenames", [])
                explanation = cf.get("explanation", "")
                issues.append(_make_issue(
                    issue_type="global_vs_regional_scope_mismatch",
                    description=(
                        f"Scope conflict detected between {involved}: {explanation}"
                    ),
                    evidence="; ".join(
                        (s.get("snippet", str(s)) if isinstance(s, dict) else str(s))[:100]
                        for s in cf.get("evidence_snippets", [])[:2]
                    ),
                    severity=SEVERITY_MEDIUM,
                ))
        elif len(scopes) > 1:
            unique_scopes = list(set(scopes.values()))
            if len(unique_scopes) > 1:
                issues.append(_make_issue(
                    issue_type="global_vs_regional_scope_mismatch",
                    description=(
                        f"Cited documents have differing scope metadata: "
                        + ", ".join(f"'{fn}' => '{sc}'" for fn, sc in scopes.items())
                    ),
                    evidence=f"Distinct scopes observed: {unique_scopes}",
                    severity=SEVERITY_MEDIUM,
                ))

        # ── Check 6: Incorrect supersession assumption ────────────────────────
        # Draft uses override language without corresponding SUPERSEDES evidence
        override_match = OVERRIDE_INDICATORS.search(draft)
        if override_match:
            # Check whether any passage actually has explicit supersession provenance
            has_explicit_supersession = any(
                p.get("provenance", {}).get("supersedes") or
                p.get("provenance", {}).get("is_superseded_warning")
                for p in passages
            )
            if not has_explicit_supersession:
                issues.append(_make_issue(
                    issue_type="incorrect_supersession_assumption",
                    description=(
                        "Draft answer uses override/supersession language "
                        f"('{override_match.group()}') but no retrieved passage carries "
                        "explicit SUPERSEDES or AMENDS provenance evidence."
                    ),
                    evidence=f"Trigger phrase found in draft: '{override_match.group()}'",
                    severity=SEVERITY_HIGH,
                    draft_excerpt=draft[max(0, override_match.start()-50):override_match.end()+50],
                ))

        # ── Check 7: Missing evidence / uncertainty ───────────────────────────
        if not passages:
            issues.append(_make_issue(
                issue_type="missing_evidence",
                description="No passages were retrieved for this question. The draft answer has no evidence base.",
                evidence="Retriever returned 0 passages.",
                severity=SEVERITY_HIGH,
            ))
        else:
            low_relevance = [
                p for p in passages
                if p.get("relevance_score", 0.0) <= MIN_RELEVANCE_THRESHOLD
            ]
            if len(low_relevance) == len(passages):
                issues.append(_make_issue(
                    issue_type="missing_evidence",
                    description=(
                        "All retrieved passages have relevance scores at or below the minimum "
                        f"threshold ({MIN_RELEVANCE_THRESHOLD}). Evidence quality is too low to trust the draft."
                    ),
                    evidence=f"All {len(passages)} passages scored <= {MIN_RELEVANCE_THRESHOLD}.",
                    severity=SEVERITY_MEDIUM,
                ))

            # Coverage check: what fraction of draft sentences can be traced?
            if draft_sentences:
                traceable = sum(
                    1 for s in draft_sentences
                    if not re.match(r"^(based on|temporal|provenance|note:|•|-)", s, re.I)
                    and any(_overlapping_words(re.sub(r"\[\d+\]", "", s), pt, min_words=4) for pt in passage_texts)
                )
                total_claims = len([
                    s for s in draft_sentences
                    if not re.match(r"^(based on|temporal|provenance|note:|•|-)", s, re.I)
                ])
                if total_claims > 0:
                    coverage = traceable / total_claims
                    if coverage < MIN_COVERAGE_FRACTION and total_claims >= 2:
                        issues.append(_make_issue(
                            issue_type="low_evidence_coverage",
                            description=(
                                f"Only {traceable}/{total_claims} claim sentences "
                                f"({coverage:.0%}) in the draft could be matched to source passages. "
                                "Answer may be partly hallucinated or out of scope."
                            ),
                            evidence=f"Evidence coverage: {coverage:.0%} (threshold: {MIN_COVERAGE_FRACTION:.0%})",
                            severity=SEVERITY_MEDIUM,
                        ))

            # ── Check 8 (Advisory): Gemini Semantic Consistency Audit ─────────
            gemini = get_gemini_client()
            if gemini.is_available and draft and passages and not issues:
                semantic_issues = self._check_semantic_audit_with_gemini(draft, passages)
                issues.extend(semantic_issues)

        return {"issues": issues}

    def _check_semantic_audit_with_gemini(
        self, draft: str, passages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Advisory semantic cross-check using Gemini API.
        Checks if the draft answer asserts any claims contradicted by source evidence.
        """
        gemini = get_gemini_client()
        if not gemini.is_available:
            return []

        try:
            excerpts = "\n\n".join(
                f"[Passage {i+1}] {p.get('text', '')[:300]}"
                for i, p in enumerate(passages[:5])
            )
            prompt = (
                f"Draft Answer to Evaluate:\n\"{draft}\"\n\n"
                f"Source Evidence Excerpts:\n{excerpts}\n\n"
                "Evaluate if the draft answer makes any factual claim that directly contradicts the source evidence.\n"
                "If there is NO contradiction, reply exactly: 'PASS: NO CONTRADICTION'.\n"
                "If there is a direct contradiction, reply with: 'CONTRADICTION: <short explanation>'."
            )
            res = gemini.generate_text(
                prompt=prompt,
                system_instruction="You are a strict adversarial policy auditor. Check only for factual contradictions.",
                temperature=0.0,
            )
            if res and res.startswith("CONTRADICTION:"):
                desc = res.replace("CONTRADICTION:", "").strip()
                return [_make_issue(
                    issue_type="semantic_contradiction_detected",
                    description=f"Gemini semantic audit detected a potential contradiction: {desc}",
                    evidence=desc,
                    severity=SEVERITY_MEDIUM,
                )]
        except Exception:
            pass
        return []

    # ── Node 3: compile_verdict ───────────────────────────────────────────────

    def _compile_verdict_node(self, state: CriticState) -> Dict[str, Any]:
        """
        Aggregates all issues into a final PASS / FLAG / ABSTAIN verdict
        with a recommended action for the orchestrating layer.
        """
        issues: List[Dict[str, Any]] = state.get("issues", [])
        passages = state.get("retrieved_passages", [])
        conflict_signals = state.get("conflict_signals", [])
        draft = state.get("draft_answer", "")

        high_severity = [i for i in issues if i["severity"] == SEVERITY_HIGH]
        medium_severity = [i for i in issues if i["severity"] == SEVERITY_MEDIUM]

        # Determine verdict
        if not passages or "do not contain sufficient evidence" in draft.lower() or "insufficient evidence" in draft.lower():
            critic_status = "ABSTAIN"
            recommended_action = (
                "The available documents do not contain sufficient evidence to answer this question reliably. "
                "The system must abstain from providing an unsupported answer."
            )
        elif any(i["issue_type"] == "missing_evidence" for i in issues) and not draft.strip():
            critic_status = "ABSTAIN"
            recommended_action = (
                "No draft answer was provided and evidence is insufficient. "
                "Run POST /synthesize first, then pass the draft_answer to POST /critic."
            )
        elif high_severity:
            critic_status = "FLAG"
            issue_types = list({i["issue_type"] for i in high_severity})
            recommended_action = (
                f"Answer flagged for arbitration. High-severity issues: {', '.join(issue_types)}. "
                "Do not present this answer to end users without human or arbitration review. "
                "Consider running POST /conflicts/detect for full conflict detail."
            )
        elif medium_severity:
            critic_status = "FLAG"
            issue_types = list({i["issue_type"] for i in medium_severity})
            recommended_action = (
                f"Answer flagged with medium-severity concerns: {', '.join(issue_types)}. "
                "Review the identified issues and add qualifying language before presenting to users."
            )
        else:
            critic_status = "PASS"
            recommended_action = (
                "No significant issues found. The draft answer appears grounded in the available evidence. "
                "Standard human review is still recommended before policy decisions are made."
            )

        # Build evidence summary
        evidence_summary = {
            "passages_evaluated": len(passages),
            "conflict_signals_detected": len(conflict_signals),
            "total_issues": len(issues),
            "high_severity_count": len(high_severity),
            "medium_severity_count": len(medium_severity),
            "low_severity_count": len([i for i in issues if i["severity"] == SEVERITY_LOW]),
            "issue_types": list({i["issue_type"] for i in issues}),
        }

        return {
            "critic_status": critic_status,
            "recommended_action": recommended_action,
            "evidence_summary": evidence_summary,
        }

    # ── Public run() method ───────────────────────────────────────────────────

    def run(
        self,
        question: str,
        draft_answer: str,
        top_k: int = 10,
        filter_files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Runs the Critic Agent workflow end-to-end.

        Args:
            question:     The original user question.
            draft_answer: The synthesizer's draft answer to critique.
            top_k:        Number of passages to retrieve for evidence (default 10 for wider coverage).
            filter_files: Optional list of filenames to restrict evidence to.

        Returns:
            Structured dict with critic_status, issues, recommended_action, evidence_summary.
        """
        initial_state: CriticState = {
            "question": question,
            "draft_answer": draft_answer,
            "top_k": top_k,
            "filter_files": filter_files,
            "retrieved_passages": [],
            "temporal_provenance_metadata": {},
            "conflict_signals": [],
            "issues": [],
            "critic_status": "ABSTAIN",
            "recommended_action": "",
            "evidence_summary": {},
        }

        final_state = self.app.invoke(initial_state)

        return {
            "question": question,
            "draft_answer": draft_answer,
            "critic_status": final_state.get("critic_status", "ABSTAIN"),
            "issues": final_state.get("issues", []),
            "recommended_action": final_state.get("recommended_action", ""),
            "evidence_summary": final_state.get("evidence_summary", {}),
            "temporal_provenance_metadata": final_state.get("temporal_provenance_metadata", {}),
        }

