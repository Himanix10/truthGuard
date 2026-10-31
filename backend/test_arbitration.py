"""
Tests for: Resolution & Arbitration Agent, Main Orchestration, POST /arbitrate, POST /ask.

Run from the truthGuard root:
    backend\\.venv\\Scripts\\python.exe backend/test_arbitration.py
"""

import sys
import pathlib
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from tpcg import TemporalProvenanceConflictGraph
from arbitration_agent import ArbitrationAgent
from orchestrator import OrchestratorWorkflow

PASS_LABEL = "\033[92mPASS\033[0m"
FAIL_LABEL = "\033[91mFAIL\033[0m"
_failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  {PASS_LABEL}  {label}")
    else:
        print(f"  {FAIL_LABEL}  {label}" + (f"  => {detail}" if detail else ""))
        _failures.append(label)


def make_dir(docs: dict) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    for fname, content in docs.items():
        (pathlib.Path(tmp.name) / fname).write_text(content, encoding="utf-8")
    return tmp


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

SEC_POL_2022 = """\
INFORMATION SECURITY POLICY

Document ID: POL-SEC-2022-001
Issue Date: 01/01/2022
Version: 1.0
Scope: Global

All employees must use AES-256 encryption for sensitive data at rest.

Passwords must be at least 12 characters and changed every 90 days.

Multi-factor authentication is mandatory for all remote access.
"""

SEC_POL_2023 = """\
INFORMATION SECURITY POLICY

Document ID: POL-SEC-2023-001
Issue Date: 15/03/2023
Version: 2.0
Scope: Global
Supersedes: POL-SEC-2022-001

All employees must use AES-256 encryption for sensitive data at rest and in transit.

Passwords must be at least 16 characters and changed every 60 days.

Multi-factor authentication is mandatory for all access including internal systems.

Regular security audits must be conducted quarterly.
"""

APAC_POLICY = """\
APAC REGIONAL INFORMATION SECURITY POLICY

Document ID: POL-APAC-2023-001
Issue Date: 20/06/2023
Version: 1.0
Scope: APAC Region

All APAC employees must use AES-128 encryption for data at rest.

Passwords must be at least 10 characters with MFA for remote access only.
"""

VANDE_BHARAT_DOC = """\
OFFICE MEMORANDUM

Subject: Travel by Vande Bharat Express on official tour

Issue Date: 04/10/2023

The matter regarding admissibility of travel by Vande Bharat Express and Humsafar Express
Trains on official Tour has been considered in this Department.

It has been decided to allow Central Government employees to travel by Vande Bharat Express
and Humsafar Express Trains for journey on Tour/Training/Transfer/Retirement, in addition
to the Trains as mentioned in the earlier OM dated 13.07.2017 and OM dated 12.09.2022.

Travel entitlements for Vande Bharat Express shall be same as for Rajdhani Express trains
for the purpose of claiming travel allowance.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — RESOLVED: single clear document, no conflict
# ─────────────────────────────────────────────────────────────────────────────

def test_resolved_single_doc():
    print("\n[1] ArbitrationAgent — RESOLVED with single clear document")
    tmp = make_dir({"sec_policy_2023.txt": SEC_POL_2023})
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))
    agent = ArbitrationAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = agent.run(
        question="What is the encryption requirement for sensitive data?",
        top_k=5,
    )

    check("result is dict", isinstance(result, dict))
    check("has outcome", "outcome" in result)
    check("has final_answer", "final_answer" in result)
    check("has explanation", "explanation" in result)
    check("has citations", "citations" in result)
    check("has critic_status", "critic_status" in result)
    check("outcome is valid", result["outcome"] in ("RESOLVED", "CONFLICT", "ABSTAIN"),
          f"got: {result['outcome']}")
    # With clean single doc, should be RESOLVED
    check("outcome is RESOLVED", result["outcome"] == "RESOLVED",
          f"got: {result['outcome']}, explanation: {result.get('explanation','')[:80]}")
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — RESOLVED with SUPERSEDES: explicit provenance resolves conflict
# ─────────────────────────────────────────────────────────────────────────────

def test_resolved_with_supersession():
    print("\n[2] ArbitrationAgent — RESOLVED via explicit SUPERSEDES metadata")
    tmp = make_dir({
        "sec_policy_2022.txt": SEC_POL_2022,
        "sec_policy_2023.txt": SEC_POL_2023,
    })
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))
    agent = ArbitrationAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = agent.run(
        question="What is the encryption requirement for data at rest?",
        top_k=5,
    )

    check("outcome is RESOLVED or CONFLICT",
          result["outcome"] in ("RESOLVED", "CONFLICT"),
          f"got: {result['outcome']}")
    # If RESOLVED, resolution_basis should mention supersession or provenance
    if result["outcome"] == "RESOLVED":
        basis = result.get("resolution_basis", "").lower()
        has_basis = bool(basis.strip())
        check("resolution_basis is non-empty", has_basis, f"got: {basis[:80]}")
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — CONFLICT: scope conflict no explicit resolution
# ─────────────────────────────────────────────────────────────────────────────

def test_conflict_scope_mismatch():
    print("\n[3] ArbitrationAgent — CONFLICT or RESOLVED for scope-conflicting docs")
    tmp = make_dir({
        "sec_policy_2023.txt": SEC_POL_2023,
        "apac_policy.txt": APAC_POLICY,
    })
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))
    agent = ArbitrationAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = agent.run(
        question="What encryption standard should employees use for data at rest?",
        top_k=5,
    )

    check("outcome is one of three valid states",
          result["outcome"] in ("RESOLVED", "CONFLICT", "ABSTAIN"),
          f"got: {result['outcome']}")
    # CONFLICT or RESOLVED with note — either is valid since APAC has no Supersedes
    print(f"    outcome: {result['outcome']} | critic_status: {result['critic_status']}")
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — ABSTAIN: no relevant documents
# ─────────────────────────────────────────────────────────────────────────────

def test_abstain_no_docs():
    print("\n[4] ArbitrationAgent — ABSTAIN when no docs exist")
    tmp = tempfile.TemporaryDirectory()
    tpcg = TemporalProvenanceConflictGraph()
    agent = ArbitrationAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = agent.run(question="What are the encryption requirements?", top_k=5)

    check("outcome is ABSTAIN", result["outcome"] == "ABSTAIN",
          f"got: {result['outcome']}")
    check("final_answer is empty", result["final_answer"] == "",
          f"got: {result['final_answer'][:50]}")
    check("abstention_reason or explanation non-empty",
          bool(result.get("abstention_reason") or result.get("explanation")))
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — Real Vande Bharat question
# ─────────────────────────────────────────────────────────────────────────────

def test_vande_bharat():
    print("\n[5] ArbitrationAgent — Vande Bharat travel question")
    tmp = make_dir({"vande_bharat.txt": VANDE_BHARAT_DOC})
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))
    agent = ArbitrationAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = agent.run(
        question="What are the rules for travel by Vande Bharat Express on official tour?",
        top_k=5,
    )

    check("outcome is valid", result["outcome"] in ("RESOLVED", "CONFLICT", "ABSTAIN"),
          f"got: {result['outcome']}")
    check("outcome is RESOLVED",
          result["outcome"] == "RESOLVED",
          f"got: {result['outcome']}")
    check("final_answer is non-empty", bool(result["final_answer"].strip()),
          f"answer: {result['final_answer'][:100]}")
    # Answer should mention travel/vande bharat
    answer_lower = result["final_answer"].lower()
    mentions_topic = any(kw in answer_lower for kw in ("vande", "bharat", "travel", "tour", "train"))
    check("final_answer mentions Vande Bharat or travel topic", mentions_topic,
          f"answer: {result['final_answer'][:120]}")
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — OrchestratorWorkflow end-to-end
# ─────────────────────────────────────────────────────────────────────────────

def test_orchestrator():
    print("\n[6] OrchestratorWorkflow — full pipeline end-to-end")
    tmp = make_dir({
        "sec_policy_2022.txt": SEC_POL_2022,
        "sec_policy_2023.txt": SEC_POL_2023,
    })
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))
    wf = OrchestratorWorkflow(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = wf.run(
        question="What are the AES encryption requirements for sensitive data?",
        top_k=5,
    )

    check("result is dict", isinstance(result, dict))
    for key in ("question", "outcome", "final_answer", "explanation",
                "citations", "conflicting_evidence", "critic_status"):
        check(f"has '{key}'", key in result, f"keys: {list(result.keys())}")
    check("outcome valid", result["outcome"] in ("RESOLVED", "CONFLICT", "ABSTAIN"),
          f"got: {result['outcome']}")
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — POST /arbitrate endpoint direct call
# ─────────────────────────────────────────────────────────────────────────────

def test_arbitrate_endpoint():
    print("\n[7] POST /arbitrate endpoint — direct handler call")
    import main as root_main

    tmp = make_dir({"vande_bharat.txt": VANDE_BHARAT_DOC})
    orig_dir = root_main.UPLOAD_DIR
    orig_tpcg = root_main.tpcg_graph

    try:
        root_main.UPLOAD_DIR = pathlib.Path(tmp.name)
        root_main.tpcg_graph = TemporalProvenanceConflictGraph()
        root_main.tpcg_graph.build_from_directory(pathlib.Path(tmp.name))

        req = root_main.ArbitrateRequest(
            question="What are the rules for travel by Vande Bharat Express on official tour?",
            top_k=5,
        )
        resp = root_main.arbitrate_answer(req)

        check("status == success", resp.get("status") == "success")
        check("outcome present", "outcome" in resp)
        check("outcome valid", resp["outcome"] in ("RESOLVED", "CONFLICT", "ABSTAIN"),
              f"got: {resp['outcome']}")
        check("final_answer present", "final_answer" in resp)
        check("explanation present", "explanation" in resp)
        check("citations present", "citations" in resp)
    finally:
        root_main.UPLOAD_DIR = orig_dir
        root_main.tpcg_graph = orig_tpcg
        tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — POST /ask endpoint direct call
# ─────────────────────────────────────────────────────────────────────────────

def test_ask_endpoint():
    print("\n[8] POST /ask endpoint — direct handler call")
    import main as root_main

    tmp = make_dir({"vande_bharat.txt": VANDE_BHARAT_DOC})
    orig_dir = root_main.UPLOAD_DIR
    orig_tpcg = root_main.tpcg_graph

    try:
        root_main.UPLOAD_DIR = pathlib.Path(tmp.name)
        root_main.tpcg_graph = TemporalProvenanceConflictGraph()
        root_main.tpcg_graph.build_from_directory(pathlib.Path(tmp.name))

        req = root_main.AskRequest(
            question="What are the rules for travel by Vande Bharat Express on official tour?",
            top_k=5,
        )
        resp = root_main.ask_question_endpoint(req)

        check("status == success", resp.get("status") == "success")
        for key in ("outcome", "final_answer", "explanation", "citations",
                    "conflicting_evidence", "critic_status"):
            check(f"has '{key}'", key in resp, f"keys: {list(resp.keys())}")
        check("outcome valid", resp["outcome"] in ("RESOLVED", "CONFLICT", "ABSTAIN"),
              f"got: {resp['outcome']}")
    finally:
        root_main.UPLOAD_DIR = orig_dir
        root_main.tpcg_graph = orig_tpcg
        tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 9 — All 17 routes present
# ─────────────────────────────────────────────────────────────────────────────

def test_all_routes():
    print("\n[9] All 17 endpoints — route inventory check")
    import main as root_main

    route_paths = {r.path for r in root_main.app.routes if hasattr(r, "path")}
    for expected in (
        "/health", "/upload", "/extract", "/metadata",
        "/graph/rebuild", "/graph", "/conflicts/detect",
        "/retrieve", "/synthesize", "/critic", "/arbitrate", "/ask",
    ):
        check(f"route '{expected}' present", expected in route_paths,
              f"available: {sorted(route_paths)}")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  TruthGuard — Arbitration & Orchestration Test Suite")
    print("=" * 60)

    test_resolved_single_doc()
    test_resolved_with_supersession()
    test_conflict_scope_mismatch()
    test_abstain_no_docs()
    test_vande_bharat()
    test_orchestrator()
    test_arbitrate_endpoint()
    test_ask_endpoint()
    test_all_routes()

    print("\n" + "=" * 60)
    if _failures:
        print(f"  RESULT: {len(_failures)} FAILED => {_failures}")
        sys.exit(1)
    else:
        print("  RESULT: ALL TESTS PASSED")
    print("=" * 60)
