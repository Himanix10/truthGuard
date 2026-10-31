"""
Tests for the Synthesizer Agent and POST /synthesize endpoint.

Run from the truthGuard root:
    backend\\.venv\\Scripts\\python.exe backend/test_synthesizer.py
"""

import sys
import os
import tempfile
import pathlib
import json

# Allow flat imports (backend/ as root)
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from tpcg import TemporalProvenanceConflictGraph
from synthesizer_agent import SynthesizerAgent

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {label}")
    else:
        msg = f"  {FAIL}  {label}" + (f"  => {detail}" if detail else "")
        print(msg)
        _failures.append(label)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: two security-policy documents with SUPERSEDES relationship
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

Data classification: Confidential data must not leave the corporate network without approved VPN.

Regular security audits must be conducted quarterly.
"""


def make_upload_dir(docs: dict) -> tempfile.TemporaryDirectory:
    """Write doc texts to a temp dir and return (tmpdir_obj, path)."""
    tmp = tempfile.TemporaryDirectory()
    for fname, content in docs.items():
        (pathlib.Path(tmp.name) / fname).write_text(content, encoding="utf-8")
    return tmp


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Sufficient evidence: encryption query matches both policies
# ─────────────────────────────────────────────────────────────────────────────

def test_sufficient_evidence():
    print("\n[1] SynthesizerAgent — sufficient evidence (encryption question)")
    tmp = make_upload_dir({
        "sec_policy_2022.txt": SEC_POL_2022,
        "sec_policy_2023.txt": SEC_POL_2023,
    })

    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))

    agent = SynthesizerAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))
    result = agent.run(
        question="What are the encryption requirements for sensitive data?",
        top_k=5,
    )

    check("result is a dict", isinstance(result, dict))
    check("has question key", "question" in result)
    check("has draft_answer", "draft_answer" in result)
    check("has citations", "citations" in result)
    check("has retrieved_evidence", "retrieved_evidence" in result)
    check("has is_sufficiently_supported", "is_sufficiently_supported" in result)
    check("has temporal_provenance_metadata", "temporal_provenance_metadata" in result)

    check("is_sufficiently_supported is True", result["is_sufficiently_supported"] is True,
          f"got {result['is_sufficiently_supported']}")
    check("draft_answer is non-empty string", bool(result["draft_answer"].strip()),
          f"got: {result['draft_answer'][:80]!r}")
    check("citations is non-empty list", isinstance(result["citations"], list) and len(result["citations"]) > 0,
          f"got {result['citations']}")

    # Citation structure
    if result["citations"]:
        c = result["citations"][0]
        for key in ("citation_id", "filename", "document_title", "passage_id", "quoted_snippet"):
            check(f"citation has '{key}'", key in c, f"citation keys: {list(c.keys())}")

    check("draft_answer mentions AES or encryption",
          any(kw in result["draft_answer"].lower() for kw in ("aes", "encrypt", "256")),
          f"answer: {result['draft_answer'][:120]!r}")

    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Insufficient evidence: completely unrelated query
# ─────────────────────────────────────────────────────────────────────────────

def test_insufficient_evidence():
    print("\n[2] SynthesizerAgent — insufficient evidence (unrelated query)")
    tmp = make_upload_dir({
        "sec_policy_2022.txt": SEC_POL_2022,
    })

    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))

    agent = SynthesizerAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))
    result = agent.run(
        question="What is the cafeteria menu for Tuesday?",
        top_k=5,
    )

    check("is_sufficiently_supported is False", result["is_sufficiently_supported"] is False,
          f"got {result['is_sufficiently_supported']}")
    check("draft_answer indicates insufficient evidence",
          any(kw in result["draft_answer"].lower()
              for kw in ("insufficient", "not support", "do not support", "cannot", "no relevant",
                         "do not contain", "not contain")),
          f"answer: {result['draft_answer'][:120]!r}")

    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — SUPERSEDES provenance note in answer
# ─────────────────────────────────────────────────────────────────────────────

def test_supersession_provenance():
    print("\n[3] SynthesizerAgent — SUPERSEDES provenance reflected in metadata")
    tmp = make_upload_dir({
        "sec_policy_2022.txt": SEC_POL_2022,
        "sec_policy_2023.txt": SEC_POL_2023,
    })

    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))

    agent = SynthesizerAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))
    # Use "encryption" — a word that appears literally in both policy fixtures
    result = agent.run(
        question="What is the encryption requirement for data at rest?",
        top_k=5,
    )

    check("is_sufficiently_supported is True", result["is_sufficiently_supported"] is True,
          f"draft: {result['draft_answer'][:120]!r}")

    # At least one piece of retrieved evidence should be returned
    evidence_list = result.get("retrieved_evidence", [])
    check("retrieved_evidence is non-empty", len(evidence_list) > 0,
          f"got {len(evidence_list)} passages")

    # Each annotated passage should carry provenance info
    has_provenance = any("provenance" in e for e in evidence_list)
    check("at least one evidence item has 'provenance'", has_provenance,
          f"evidence keys: {[list(e.keys()) for e in evidence_list[:2]]}")

    # With two docs and explicit SUPERSEDES, the temporal note should mention supersession
    draft = result["draft_answer"].lower()
    has_temporal_note = any(kw in draft for kw in ("supersed", "temporal", "note", "provenance"))
    check("draft_answer contains temporal/supersession note", has_temporal_note,
          f"draft: {result['draft_answer'][:200]!r}")

    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — Endpoint: main.synthesize_answer() via direct call
# ─────────────────────────────────────────────────────────────────────────────

def test_endpoint_direct():
    print("\n[4] POST /synthesize endpoint — direct handler invocation")
    import main as root_main

    # Patch UPLOAD_DIR and tpcg_graph to a controlled temp dir
    tmp = make_upload_dir({"sec_policy_2022.txt": SEC_POL_2022})
    original_upload_dir = root_main.UPLOAD_DIR
    original_tpcg = root_main.tpcg_graph

    try:
        root_main.UPLOAD_DIR = pathlib.Path(tmp.name)
        root_main.tpcg_graph = TemporalProvenanceConflictGraph()
        root_main.tpcg_graph.build_from_directory(pathlib.Path(tmp.name))

        # Call the endpoint handler directly with a SynthesizeRequest
        req = root_main.SynthesizeRequest(
            question="What are the encryption requirements for sensitive data?",
            top_k=3,
        )
        result = root_main.synthesize_answer(req)

        check("returns a dict", isinstance(result, dict))
        check("status == success", result.get("status") == "success",
              f"got: {result.get('status')}")
        check("draft_answer present", "draft_answer" in result)
        check("citations present", "citations" in result)
        check("is_sufficiently_supported present", "is_sufficiently_supported" in result)
    finally:
        root_main.UPLOAD_DIR = original_upload_dir
        root_main.tpcg_graph = original_tpcg
        tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — All existing endpoints still importable / intact
# ─────────────────────────────────────────────────────────────────────────────

def test_existing_routes_intact():
    print("\n[5] Existing endpoints — route inventory check")
    import main as root_main

    route_paths = {
        r.path for r in root_main.app.routes if hasattr(r, "path")
    }
    for expected in ("/health", "/upload", "/extract", "/metadata",
                     "/graph/rebuild", "/graph", "/conflicts/detect",
                     "/retrieve", "/synthesize"):
        check(f"route '{expected}' present", expected in route_paths,
              f"available: {sorted(route_paths)}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — Empty question raises validation error (no crash)
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_question_raises():
    print("\n[6] SynthesizerAgent — empty question handling")
    tmp = make_upload_dir({"sec_policy_2022.txt": SEC_POL_2022})
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.build_from_directory(pathlib.Path(tmp.name))
    agent = SynthesizerAgent(tpcg=tpcg, upload_dir=pathlib.Path(tmp.name))

    # agent.run() with empty question should return is_sufficiently_supported=False
    # (the endpoint layer raises HTTP 400, but the agent itself should degrade gracefully)
    result = agent.run(question="   ", top_k=5)
    check("empty question → is_sufficiently_supported False",
          result["is_sufficiently_supported"] is False,
          f"got: {result['is_sufficiently_supported']}")
    tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  TruthGuard — Synthesizer Agent Test Suite")
    print("=" * 60)

    test_sufficient_evidence()
    test_insufficient_evidence()
    test_supersession_provenance()
    test_endpoint_direct()
    test_existing_routes_intact()
    test_empty_question_raises()

    print("\n" + "=" * 60)
    if _failures:
        print(f"  RESULT: {len(_failures)} FAILED — {_failures}")
        sys.exit(1)
    else:
        print("  RESULT: ALL TESTS PASSED")
    print("=" * 60)
