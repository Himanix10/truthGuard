"""
Unit and Integration Tests for Document Comparison Feature in TruthGuard-Chronos.
Tests POST /compare and compare_two_documents:
  1. Supersession resolution (outcome=RESOLVED)
  2. Scope conflict without explicit precedence (outcome=CONFLICT)
  3. Empty or unreadable document (outcome=ABSTAIN)
  4. Response structure and citations
"""

print("Starting test_comparator...")
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

print("Importing tpcg...")
from tpcg import TemporalProvenanceConflictGraph
print("Importing comparator...")
from comparator import compare_two_documents
print("Importing main...")
import main
print("All imports successful!")


def run_tests():
    print("=== Testing Document Comparison Feature ===")
    tpcg = TemporalProvenanceConflictGraph()

    # Document 1: 2022 policy
    tpcg.add_document_node(
        saved_filename="sec_policy_2022.txt",
        original_filename="sec_policy_2022.txt",
        metadata={
            "document_title": "Global Information Security Policy",
            "effective_date": "2022-01-01",
            "publication_or_issue_date": "2021-12-15",
            "version_number": "1.0",
            "policy_or_document_identifier": "POL-SEC-2022-001",
            "geographic_or_organizational_scope": "Global",
            "appears_amendment_or_replacement": False,
        },
        raw_text="Global Information Security Policy\nPolicy ID: POL-SEC-2022-001\nVersion: 1.0\nScope: Global\nAll corporate assets must adhere to established encryption rules AES-128.",
    )

    # Document 2: 2025 superseding policy
    tpcg.add_document_node(
        saved_filename="sec_policy_2025.txt",
        original_filename="sec_policy_2025.txt",
        metadata={
            "document_title": "Global Information Security Policy",
            "effective_date": "2025-02-01",
            "publication_or_issue_date": "2025-01-15",
            "version_number": "3.2",
            "policy_or_document_identifier": "POL-SEC-2025-009",
            "geographic_or_organizational_scope": "Global",
            "appears_amendment_or_replacement": True,
            "referenced_parent_or_previous_policy_identifier": "POL-SEC-2022-001",
        },
        raw_text="Global Information Security Policy\nPolicy ID: POL-SEC-2025-009\nVersion: 3.2\nScope: Global\nThis policy supersedes POL-SEC-2022-001.\nAll corporate assets must adhere to established encryption rules AES-256.",
    )

    # Document 3: Regional policy (Scope conflict with Doc 1)
    tpcg.add_document_node(
        saved_filename="sec_policy_apac.txt",
        original_filename="sec_policy_apac.txt",
        metadata={
            "document_title": "APAC Regional Security Standard",
            "effective_date": "2023-05-01",
            "publication_or_issue_date": "2023-04-10",
            "version_number": "1.2",
            "policy_or_document_identifier": "STD-APAC-2023-005",
            "geographic_or_organizational_scope": "APAC",
            "appears_amendment_or_replacement": False,
        },
        raw_text="APAC Regional Security Standard\nPolicy ID: STD-APAC-2023-005\nVersion: 1.2\nScope: APAC\nAll regional systems must adhere to local encryption standard DES.",
    )

    # Document 4: Empty document
    tpcg.add_document_node(
        saved_filename="empty_doc.txt",
        original_filename="empty_doc.txt",
        metadata={
            "document_title": None,
            "effective_date": None,
            "version_number": None,
            "policy_or_document_identifier": None,
            "geographic_or_organizational_scope": None,
        },
        raw_text="",
    )

    tpcg.infer_relationships()

    # 1. Test Supersession: sec_policy_2025 vs sec_policy_2022
    res_super = compare_two_documents(
        file_a="sec_policy_2025.txt",
        file_b="sec_policy_2022.txt",
        tpcg=tpcg,
        upload_dir=main.UPLOAD_DIR,
    )
    print("Test 1 - Supersession outcome:", res_super["outcome"])
    assert res_super["outcome"] == "RESOLVED", f"Expected RESOLVED, got {res_super['outcome']}"
    assert res_super["relationship"] == "SUPERSEDES", f"Expected SUPERSEDES, got {res_super['relationship']}"
    assert res_super["document_a"]["metadata"]["version"] == "3.2"
    assert res_super["document_b"]["metadata"]["version"] == "1.0"
    assert len(res_super["citations"]) >= 1
    print("[PASS] Test 1: Supersession resolved with citations and metadata")

    # 2. Test Scope Conflict: sec_policy_2022 vs sec_policy_apac
    res_conflict = compare_two_documents(
        file_a="sec_policy_2022.txt",
        file_b="sec_policy_apac.txt",
        tpcg=tpcg,
        upload_dir=main.UPLOAD_DIR,
    )
    print("Test 2 - Scope conflict outcome:", res_conflict["outcome"])
    assert res_conflict["outcome"] == "CONFLICT", f"Expected CONFLICT, got {res_conflict['outcome']}"
    assert any(d.get("is_conflicting") for d in res_conflict["differences"])
    print("[PASS] Test 2: Scope conflict accurately flagged as CONFLICT without guessing precedence")

    # 3. Test Empty Document: empty_doc vs sec_policy_2022
    res_empty = compare_two_documents(
        file_a="empty_doc.txt",
        file_b="sec_policy_2022.txt",
        tpcg=tpcg,
        upload_dir=main.UPLOAD_DIR,
    )
    print("Test 3 - Empty document outcome:", res_empty["outcome"])
    assert res_empty["outcome"] == "ABSTAIN", f"Expected ABSTAIN, got {res_empty['outcome']}"
    assert res_empty["document_a"]["is_empty"] is True
    print("[PASS] Test 3: Empty document gracefully handled with ABSTAIN")

    # 4. Test API endpoint directly
    main.tpcg_graph = tpcg

    req = main.CompareRequest(file_a="sec_policy_2025.txt", file_b="sec_policy_2022.txt")
    data = main.compare_documents_endpoint(payload=req)
    assert data["outcome"] == "RESOLVED"
    assert "document_a" in data
    assert "document_b" in data
    assert "differences" in data
    assert "citations" in data
    print("[PASS] Test 4: compare_documents_endpoint returned structured JSON response")

    # Test error handling on missing payload
    try:
        main.compare_documents_endpoint(payload=main.CompareRequest(file_a=""))
        assert False, "Should have raised HTTPException"
    except main.HTTPException as e:
        assert e.status_code == 400
        print("[PASS] Test 5: Validation error for missing files handled correctly with 400")

    print("\n=== ALL COMPARATOR TESTS PASSED SUCCESSFULLY! ===")


if __name__ == "__main__":
    run_tests()
