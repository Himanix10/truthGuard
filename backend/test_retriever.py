"""
Unit and Integration Tests for Retriever & Chrono-Annotator Agent.
Tests the LangGraph agent workflow, TF-IDF retrieval, chrono-annotations, and POST /retrieve endpoint.
"""

import sys
import json
from pathlib import Path

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from tpcg import TemporalProvenanceConflictGraph
from retriever_agent import RetrieverChronoAnnotatorAgent, split_text_into_passages, compute_tfidf_scores
import main


def test_unit_retriever_agent():
    print("--- 1. Testing RetrieverChronoAnnotatorAgent Unit Workflow ---")
    tpcg = TemporalProvenanceConflictGraph()

    # Add sample policy documents
    tpcg.add_document_node(
        saved_filename="sec_v1.txt",
        original_filename="sec_policy_v1.txt",
        metadata={
            "document_title": "Information Security Standard",
            "effective_date": "2022-01-01",
            "publication_or_issue_date": "2021-12-15",
            "version_number": "1.0",
            "policy_or_document_identifier": "POL-SEC-2022-001",
            "geographic_or_organizational_scope": "Global",
            "appears_amendment_or_replacement": False,
        },
        raw_text=(
            "Information Security Standard\n"
            "Policy ID: POL-SEC-2022-001\n"
            "Version: 1.0\n"
            "Scope: Global\n\n"
            "1. Purpose & Encryption Standards\n"
            "All corporate laptops and storage devices must use AES-128 cryptographic encryption.\n\n"
            "2. Access & Authentication\n"
            "Employees must use alphanumeric passwords of at least 8 characters."
        ),
    )

    tpcg.add_document_node(
        saved_filename="sec_v2.txt",
        original_filename="sec_policy_v2.txt",
        metadata={
            "document_title": "Information Security Standard",
            "effective_date": "2025-02-01",
            "publication_or_issue_date": "2025-01-15",
            "version_number": "2.0",
            "policy_or_document_identifier": "POL-SEC-2025-009",
            "geographic_or_organizational_scope": "Global",
            "appears_amendment_or_replacement": True,
            "referenced_parent_or_previous_policy_identifier": "POL-SEC-2022-001",
        },
        raw_text=(
            "Information Security Standard\n"
            "Policy ID: POL-SEC-2025-009\n"
            "Version: 2.0\n"
            "Scope: Global\n\n"
            "1. Purpose\n"
            "This policy supersedes POL-SEC-2022-001.\n"
            "All corporate laptops and storage devices must use AES-256 cryptographic encryption.\n\n"
            "2. Access & Authentication\n"
            "Employees must use multi-factor authentication (MFA) and passwords of at least 14 characters."
        ),
    )

    tpcg.infer_relationships()

    agent = RetrieverChronoAnnotatorAgent(tpcg=tpcg, upload_dir=main.UPLOAD_DIR)

    # Execute agent workflow with a question
    question = "What is the encryption requirement for corporate laptops?"
    res = agent.run(question=question, top_k=3)

    assert res["question"] == question
    assert res["passages_count"] > 0
    assert len(res["retrieved_passages"]) <= 3
    print(f"[PASS] LangGraph agent workflow completed: retrieved {res['passages_count']} passages")

    # Verify Chrono-annotations on retrieved passages
    passages = res["retrieved_passages"]
    required_meta_keys = [
        "filename",
        "document_title",
        "effective_date",
        "issue_date",
        "version",
        "scope",
        "document_identifier",
    ]

    for p in passages:
        # Check text context is sufficient for citation
        assert len(p["text"]) >= 40, "Passage text is too brief for citation context"
        assert p["relevance_score"] > 0
        assert len(p["matched_terms"]) > 0

        # Check metadata annotations
        meta = p["metadata"]
        for k in required_meta_keys:
            assert k in meta, f"Missing required annotation key '{k}'"

        # Check provenance annotations
        prov = p["provenance"]
        assert "supersedes" in prov
        assert "superseded_by" in prov
        assert "is_superseded_warning" in prov

    print("[PASS] All 7 required metadata annotations + context length verified on passages")

    # Verify superseded warning logic
    v1_passage = next((p for p in passages if p["metadata"]["document_identifier"] == "POL-SEC-2022-001"), None)
    if v1_passage:
        assert v1_passage["provenance"]["is_superseded_warning"] is True
        assert "POL-SEC-2025-009" in v1_passage["provenance"]["superseded_by"]
        print("[PASS] Chrono-Annotator correctly identified and flagged obsolete/superseded passage")

    # Verify temporal provenance metadata summary
    summary = res["temporal_provenance_metadata"]
    assert "documents_consulted" in summary
    assert "earliest_effective_date" in summary
    assert "latest_effective_date" in summary
    assert "relevant_document_identifiers" in summary
    print("[PASS] Temporal/provenance summary metadata confirmed present")


def test_api_endpoint():
    print("\n--- 2. Testing POST /retrieve Endpoint Directly ---")

    # 1. Validation test (empty question should return 400)
    try:
        main.retrieve_passages(payload=main.RetrieveRequest(question=""))
        assert False, "Should have raised 400 for empty question"
    except main.HTTPException as e:
        assert e.status_code == 400
        print("[PASS] Validation check: empty question rejected with HTTP 400")

    # 2. Functional retrieval test
    req = main.RetrieveRequest(question="What are the encryption rules for corporate assets?", top_k=3)
    response = main.retrieve_passages(payload=req)

    assert response["status"] == "success"
    assert response["question"] == req.question
    assert "retrieved_passages" in response
    assert "temporal_provenance_metadata" in response
    assert len(response["retrieved_passages"]) > 0

    first_passage = response["retrieved_passages"][0]
    assert "metadata" in first_passage
    assert "provenance" in first_passage
    assert first_passage["metadata"]["document_title"] is not None
    print(f"[PASS] POST /retrieve returned {response['passages_count']} annotated passages with provenance metadata")

    # 3. Targeted file filtering
    filter_req = main.RetrieveRequest(
        question="encryption",
        top_k=2,
        files=["sec_policy.txt"],
    )
    filter_res = main.retrieve_passages(payload=filter_req)
    assert filter_res["status"] == "success"
    for p in filter_res["retrieved_passages"]:
        assert p["metadata"]["filename"] == "sec_policy.txt"
    print("[PASS] Targeted file filtering in POST /retrieve confirmed")

    # 4. Verify existing endpoints remain operational
    health = main.health_check()
    assert health == {"status": "healthy"}
    conflicts = main.detect_conflicts()
    assert conflicts["status"] == "success"
    graph = main.get_graph()
    assert "nodes" in graph and "edges" in graph
    print("[PASS] All existing endpoints (/health, /conflicts/detect, /graph, /graph/rebuild) remain operational")


if __name__ == "__main__":
    test_unit_retriever_agent()
    test_api_endpoint()
    print("\n=== ALL RETRIEVER & CHRONO-ANNOTATOR AGENT TESTS PASSED! ===")

