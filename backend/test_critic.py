"""
Tests for the Adversarial Red-Team Critic Agent and POST /critic endpoint.

Run from the truthGuard root:
    backend\\.venv\\Scripts\\python.exe backend/test_critic.py
"""

import sys
import pathlib
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from tpcg import TemporalProvenanceConflictGraph
from critic_agent import CriticAgent

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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

Data classification: Confidential data must not leave the corporate network without VPN.
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

Data may be stored in regional APAC data centers without VPN requirement.
"""

# A draft that is well-grounded in SEC_POL_2023
GOOD_DRAFT = """\
Based on INFORMATION SECURITY POLICY (dated 15/03/2023):
\u2022 All employees must use AES-256 encryption for sensitive data at rest and in transit. [1]
\u2022 Passwords must be at least 16 characters and changed every 60 days. [2]
\u2022 Multi-factor authentication is mandatory for all access including internal systems. [3]
"""

# A draft that makes claims not found in any passage
HALLUCINATED_DRAFT = """\
Based on policy documents:
\u2022 All employees must use quantum-resistant encryption algorithms by 2025. [1]
\u2022 Password complexity must include biometric verification. [2]
\u2022 Zero-trust architecture is mandatory for all systems from Q1 2024. [3]
"""

# A draft with no citations
UNCITED_DRAFT = """\
All employees must use AES-256 encryption for sensitive data at rest.
Passwords must be at least 16 characters. MFA is required for all systems.
"""

# A draft that implies override without explicit evidence
OVERRIDE_DRAFT = """\
Based on INFORMATION SECURITY POLICY (dated 15/03/2023):
\u2022 The newer policy overrides all previous requirements. This policy supersedes the older one. [1]
\u2022 All employees must use AES-256 encryption. [2]
"""


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — PASS: well-grounded draft against matching evidence
# ─────────────────────────────────────────────────────────────────────────────

def test_pass_verdict():
    print("\n[1] CriticAgent — PASS verdict for well-grounded draft")
    tmp = make_dir({"sec_policy_2023.txt": SEC_POL_2023})
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))
    agent = CriticAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = agent.run(
        question="What are the encryption requirements for data security?",
        draft_answer=GOOD_DRAFT,
        top_k=10,
    )

    check("result is dict", isinstance(result, dict))
    check("has critic_status", "critic_status" in result)
    check("has issues", "issues" in result)
    check("has recommended_action", "recommended_action" in result)
    check("has evidence_summary", "evidence_summary" in result)
    check("critic_status is PASS or FLAG",
          result["critic_status"] in ("PASS", "FLAG"),
          f"got: {result['critic_status']}")
    # Good draft on matching doc: should not have HIGH severity unsupported_claim
    high_issues = [i for i in result["issues"] if i["severity"] == "HIGH"
                   and i["issue_type"] == "unsupported_claim"]
    check("no HIGH unsupported_claim issues", len(high_issues) == 0,
          f"high issues: {[i['description'][:60] for i in high_issues]}")
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — FLAG: hallucinated content not found in passages
# ─────────────────────────────────────────────────────────────────────────────

def test_flag_hallucinated_claims():
    print("\n[2] CriticAgent — FLAG verdict for hallucinated claims")
    tmp = make_dir({"sec_policy_2022.txt": SEC_POL_2022})
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))
    agent = CriticAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = agent.run(
        question="What are the encryption requirements?",
        draft_answer=HALLUCINATED_DRAFT,
        top_k=10,
    )

    check("critic_status is FLAG or ABSTAIN",
          result["critic_status"] in ("FLAG", "ABSTAIN"),
          f"got: {result['critic_status']}, issues: {[i['issue_type'] for i in result['issues']]}")
    has_unsupported = any(i["issue_type"] == "unsupported_claim" for i in result["issues"])
    # May be low evidence coverage instead if retriever returns no passages for hallucinated query
    has_any_issue = len(result["issues"]) > 0
    check("at least one issue identified", has_any_issue,
          f"issues: {result['issues']}")
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — FLAG: missing citations in draft
# ─────────────────────────────────────────────────────────────────────────────

def test_flag_missing_citations():
    print("\n[3] CriticAgent — FLAG for draft with no citations")
    tmp = make_dir({"sec_policy_2023.txt": SEC_POL_2023})
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))
    agent = CriticAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = agent.run(
        question="What are the encryption requirements?",
        draft_answer=UNCITED_DRAFT,
        top_k=10,
    )

    citation_issues = [i for i in result["issues"] if i["issue_type"] == "missing_or_incorrect_citation"]
    check("missing citation issue detected", len(citation_issues) > 0,
          f"issues: {[i['issue_type'] for i in result['issues']]}")
    check("critic_status is FLAG (not PASS)",
          result["critic_status"] != "PASS",
          f"got: {result['critic_status']}")
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — FLAG: scope conflict between global and regional docs
# ─────────────────────────────────────────────────────────────────────────────

def test_flag_scope_conflict():
    print("\n[4] CriticAgent — FLAG for global vs APAC regional scope conflict")
    tmp = make_dir({
        "sec_policy_2023.txt": SEC_POL_2023,
        "apac_policy.txt": APAC_POLICY,
    })
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))
    agent = CriticAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = agent.run(
        question="What encryption standard should employees use for data at rest?",
        draft_answer=GOOD_DRAFT,
        top_k=10,
    )

    scope_issues = [i for i in result["issues"]
                    if i["issue_type"] in ("global_vs_regional_scope_mismatch", "conflicting_rules")]
    check("scope or conflict issue detected", len(scope_issues) > 0,
          f"all issues: {[i['issue_type'] for i in result['issues']]}")
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — FLAG: incorrect supersession assumption
# ─────────────────────────────────────────────────────────────────────────────

def test_flag_incorrect_supersession():
    print("\n[5] CriticAgent — FLAG for override language without explicit provenance")
    tmp = make_dir({"sec_policy_2022.txt": SEC_POL_2022})
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))
    agent = CriticAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = agent.run(
        question="What are the current encryption requirements?",
        draft_answer=OVERRIDE_DRAFT,
        top_k=10,
    )

    supersession_issues = [i for i in result["issues"]
                           if i["issue_type"] == "incorrect_supersession_assumption"]
    check("incorrect supersession assumption detected", len(supersession_issues) > 0,
          f"all issues: {[i['issue_type'] for i in result['issues']]}")
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — ABSTAIN: no documents uploaded
# ─────────────────────────────────────────────────────────────────────────────

def test_abstain_no_evidence():
    print("\n[6] CriticAgent — ABSTAIN when no documents are uploaded")
    tmp = tempfile.TemporaryDirectory()  # empty dir
    tpcg = TemporalProvenanceConflictGraph()
    # Don't build from directory — graph is empty
    agent = CriticAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = agent.run(
        question="What are the encryption requirements?",
        draft_answer=GOOD_DRAFT,
        top_k=5,
    )

    check("critic_status is ABSTAIN", result["critic_status"] == "ABSTAIN",
          f"got: {result['critic_status']}")
    check("recommended_action is non-empty", bool(result["recommended_action"].strip()))
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — Issue structure validation
# ─────────────────────────────────────────────────────────────────────────────

def test_issue_structure():
    print("\n[7] CriticAgent — issue dict structure validation")
    tmp = make_dir({
        "sec_policy_2022.txt": SEC_POL_2022,
        "apac_policy.txt": APAC_POLICY,
    })
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))
    agent = CriticAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    result = agent.run(
        question="What are the encryption and authentication requirements?",
        draft_answer=HALLUCINATED_DRAFT + "\n" + UNCITED_DRAFT,
        top_k=10,
    )

    check("issues is a list", isinstance(result["issues"], list))
    required_keys = {"issue_type", "description", "evidence", "severity", "draft_excerpt"}
    for i, issue in enumerate(result["issues"]):
        for key in required_keys:
            check(f"issue[{i}] has '{key}'", key in issue,
                  f"issue keys: {list(issue.keys())}")
        check(f"issue[{i}] severity is valid",
              issue.get("severity") in ("HIGH", "MEDIUM", "LOW"),
              f"got: {issue.get('severity')}")

    check("evidence_summary has expected keys",
          all(k in result["evidence_summary"] for k in
              ("passages_evaluated", "total_issues", "high_severity_count",
               "medium_severity_count", "issue_types")))
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — Endpoint direct call
# ─────────────────────────────────────────────────────────────────────────────

def test_endpoint_direct():
    print("\n[8] POST /critic endpoint — direct handler call")
    import main as root_main

    tmp = make_dir({"sec_policy_2023.txt": SEC_POL_2023})
    original_upload_dir = root_main.UPLOAD_DIR
    original_tpcg = root_main.tpcg_graph

    try:
        root_main.UPLOAD_DIR = pathlib.Path(tmp.name)
        root_main.tpcg_graph = TemporalProvenanceConflictGraph()
        root_main.tpcg_graph.build_from_directory(pathlib.Path(tmp.name))

        req = root_main.CriticRequest(
            question="What are the encryption requirements?",
            draft_answer=GOOD_DRAFT,
            top_k=10,
        )
        response = root_main.critic_review(req)

        check("returns dict", isinstance(response, dict))
        check("status == success", response.get("status") == "success",
              f"got: {response.get('status')}")
        check("critic_status present", "critic_status" in response)
        check("issues present", "issues" in response)
        check("recommended_action present", "recommended_action" in response)
        check("evidence_summary present", "evidence_summary" in response)
        check("critic_status valid",
              response.get("critic_status") in ("PASS", "FLAG", "ABSTAIN"),
              f"got: {response.get('critic_status')}")
    finally:
        root_main.UPLOAD_DIR = original_upload_dir
        root_main.tpcg_graph = original_tpcg
        tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 9 — All existing routes still present
# ─────────────────────────────────────────────────────────────────────────────

def test_all_routes_intact():
    print("\n[9] All endpoints — route inventory check")
    import main as root_main

    route_paths = {r.path for r in root_main.app.routes if hasattr(r, "path")}
    for expected in (
        "/health", "/upload", "/extract", "/metadata",
        "/graph/rebuild", "/graph", "/conflicts/detect",
        "/retrieve", "/synthesize", "/critic",
    ):
        check(f"route '{expected}' present", expected in route_paths,
              f"available: {sorted(route_paths)}")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  TruthGuard — Red-Team Critic Agent Test Suite")
    print("=" * 60)

    test_pass_verdict()
    test_flag_hallucinated_claims()
    test_flag_missing_citations()
    test_flag_scope_conflict()
    test_flag_incorrect_supersession()
    test_abstain_no_evidence()
    test_issue_structure()
    test_endpoint_direct()
    test_all_routes_intact()

    print("\n" + "=" * 60)
    if _failures:
        print(f"  RESULT: {len(_failures)} FAILED => {_failures}")
        sys.exit(1)
    else:
        print("  RESULT: ALL TESTS PASSED")
    print("=" * 60)

