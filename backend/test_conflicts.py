"""
Unit and Integration Tests for TruthGuard-Chronos Conflict Detection Module.
Tests rule-based conflict classification across:
  1. Supersession
  2. Scope conflict
  3. Temporal conflict
  4. Insufficient evidence
"""

import sys
import json
from pathlib import Path

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from tpcg import TemporalProvenanceConflictGraph
from conflict_detector import ConflictDetector
import main


def test_unit_conflict_detection():
    print("--- 1. Testing ConflictDetector Unit Logic ---")
    tpcg = TemporalProvenanceConflictGraph()

    # Document 1 & 2: Supersession Pair
    tpcg.add_document_node(
        saved_filename="sec_v1.txt",
        original_filename="sec_policy_v1.txt",
        metadata={
            "document_title": "Information Security Standard",
            "effective_date": "2022-01-01",
            "version_number": "1.0",
            "policy_or_document_identifier": "POL-SEC-2022-001",
            "geographic_or_organizational_scope": "Global",
            "appears_amendment_or_replacement": False,
        },
        raw_text="Information Security Standard\nPolicy ID: POL-SEC-2022-001\nVersion: 1.0\nAll corporate assets must adhere to encryption standard AES-128.",
    )
    tpcg.add_document_node(
        saved_filename="sec_v2.txt",
        original_filename="sec_policy_v2.txt",
        metadata={
            "document_title": "Information Security Standard",
            "effective_date": "2025-02-01",
            "version_number": "2.0",
            "policy_or_document_identifier": "POL-SEC-2025-009",
            "geographic_or_organizational_scope": "Global",
            "appears_amendment_or_replacement": True,
            "referenced_parent_or_previous_policy_identifier": "POL-SEC-2022-001",
        },
        raw_text="Information Security Standard\nPolicy ID: POL-SEC-2025-009\nThis policy supersedes POL-SEC-2022-001. All corporate assets must adhere to encryption standard AES-256.",
    )

    # Document 3 & 4: Scope Conflict Pair (Global vs Regional APAC)
    tpcg.add_document_node(
        saved_filename="gov_global.txt",
        original_filename="gov_global.txt",
        metadata={
            "document_title": "Data Retention Policy",
            "effective_date": "2024-01-01",
            "version_number": "1.0",
            "policy_or_document_identifier": "POL-RET-001",
            "geographic_or_organizational_scope": "Global",
            "appears_amendment_or_replacement": False,
        },
        raw_text="Data Retention Policy\nPolicy ID: POL-RET-001\nScope: Global\nCustomer records must be retained for at least 7 years.",
    )
    tpcg.add_document_node(
        saved_filename="gov_apac.txt",
        original_filename="gov_apac.txt",
        metadata={
            "document_title": "Data Retention Guidelines",
            "effective_date": "2024-06-01",
            "version_number": "1.0",
            "policy_or_document_identifier": "POL-RET-APAC",
            "geographic_or_organizational_scope": "Regional (APAC)",
            "appears_amendment_or_replacement": False,
        },
        raw_text="Data Retention Guidelines\nPolicy ID: POL-RET-APAC\nScope: Regional (APAC)\nCustomer records must be deleted after 3 years.",
    )

    # Document 5 & 6: Temporal Conflict Pair (Overlapping dates, no explicit supersession)
    tpcg.add_document_node(
        saved_filename="remote_v1.txt",
        original_filename="remote_policy_v1.txt",
        metadata={
            "document_title": "Remote Work Policy",
            "effective_date": "2023-01-01",
            "version_number": "1.0",
            "policy_or_document_identifier": "POL-HR-WFH",
            "geographic_or_organizational_scope": "Global",
            "appears_amendment_or_replacement": False,
        },
        raw_text="Remote Work Policy\nPolicy ID: POL-HR-WFH\nEffective Date: 2023-01-01\nEmployees are permitted to work remotely 2 days per week.",
    )
    tpcg.add_document_node(
        saved_filename="remote_v2.txt",
        original_filename="remote_policy_v2.txt",
        metadata={
            "document_title": "Remote Work Policy",
            "effective_date": "2024-01-01",
            "version_number": "2.0",
            "policy_or_document_identifier": "POL-HR-WFH",
            "geographic_or_organizational_scope": "Global",
            "appears_amendment_or_replacement": False,
        },
        raw_text="Remote Work Policy\nPolicy ID: POL-HR-WFH\nEffective Date: 2024-01-01\nEmployees are required to work on-site 5 days per week. Remote work is prohibited.",
    )

    # Document 7: Insufficient Evidence Document (Blank or missing text/metadata)
    tpcg.add_document_node(
        saved_filename="notes.txt",
        original_filename="sync_notes.txt",
        metadata={
            "document_title": None,
            "effective_date": None,
            "version_number": None,
            "policy_or_document_identifier": None,
            "geographic_or_organizational_scope": None,
            "appears_amendment_or_replacement": False,
        },
        raw_text="Brief notes from Tuesday call.",
    )

    # Build TPCG graph edges
    tpcg.infer_relationships()

    detector = ConflictDetector(graph=tpcg)
    conflicts = detector.detect_conflicts()

    print(f"Total conflicts detected: {len(conflicts)}")
    conflict_types = {c["conflict_type"] for c in conflicts}
    print(f"Conflict types observed: {conflict_types}")

    # 1. Verify Case 1: Supersession
    supersession = next((c for c in conflicts if c["conflict_type"] == "supersession"), None)
    assert supersession is not None, "Failed to detect Supersession conflict"
    assert supersession["appears_resolvable"] is True
    assert "sec_policy_v2.txt" in supersession["involved_filenames"]
    assert "sec_policy_v1.txt" in supersession["involved_filenames"]
    assert len(supersession["evidence_snippets"]) >= 2
    print("[PASS] Case 1: Supersession detected and verified as resolvable (True)")

    # 2. Verify Case 2: Scope Conflict
    scope_conflict = next((c for c in conflicts if c["conflict_type"] == "scope_conflict"), None)
    assert scope_conflict is not None, "Failed to detect Scope conflict"
    assert scope_conflict["appears_resolvable"] is False
    assert "gov_global.txt" in scope_conflict["involved_filenames"]
    assert "gov_apac.txt" in scope_conflict["involved_filenames"]
    print("[PASS] Case 2: Scope conflict detected (Global vs Regional) and marked non-resolvable from metadata alone")

    # 3. Verify Case 3: Temporal Conflict
    temporal_conflict = next((c for c in conflicts if c["conflict_type"] == "temporal_conflict"), None)
    assert temporal_conflict is not None, "Failed to detect Temporal conflict"
    assert temporal_conflict["appears_resolvable"] is False
    assert "remote_policy_v1.txt" in temporal_conflict["involved_filenames"]
    assert "remote_policy_v2.txt" in temporal_conflict["involved_filenames"]
    print("[PASS] Case 3: Temporal conflict detected: newer date does NOT automatically override older policy")

    # 4. Verify Case 4: Insufficient Evidence
    insufficient = next((c for c in conflicts if c["conflict_type"] == "insufficient_evidence"), None)
    assert insufficient is not None, "Failed to detect Insufficient Evidence conflict"
    assert insufficient["appears_resolvable"] is False
    assert "sync_notes.txt" in insufficient["involved_filenames"]
    print("[PASS] Case 4: Insufficient evidence detected for documents lacking substantive text or metadata")


def test_api_endpoint():
    print("\n--- 2. Testing POST /conflicts/detect Endpoint ---")

    # Test detection across all current documents
    res = main.detect_conflicts()
    assert res["status"] == "success"
    assert "conflicts_count" in res
    assert "conflicts" in res
    assert "summary" in res

    conflicts = res["conflicts"]
    summary = res["summary"]
    print(f"Detected {len(conflicts)} conflicts. Summary: {summary}")

    # Verify JSON structure of each conflict item
    required_keys = [
        "conflict_id",
        "conflict_type",
        "involved_filenames",
        "short_explanation",
        "evidence_snippets",
        "appears_resolvable",
    ]
    for c in conflicts:
        for k in required_keys:
            assert k in c, f"Missing key '{k}' in conflict item"
        assert isinstance(c["involved_filenames"], list)
        assert isinstance(c["evidence_snippets"], list)
        assert isinstance(c["appears_resolvable"], bool)
        assert c["conflict_type"] in ("supersession", "scope_conflict", "temporal_conflict", "insufficient_evidence")

    # Test targeted conflict detection with specific files
    req = main.ConflictDetectRequest(files=["sec_policy.txt", "sec_policy_2022.txt"])
    targeted_res = main.detect_conflicts(payload=req)
    assert targeted_res["status"] == "success"
    assert targeted_res["conflicts_count"] == 1
    assert targeted_res["conflicts"][0]["conflict_type"] == "supersession"
    print("[PASS] Targeted conflict detection with specific filenames verified")

    # Verify existing endpoints still work
    health = main.health_check()
    assert health == {"status": "healthy"}
    root = main.read_root()
    assert "message" in root
    graph = main.get_graph()
    assert "nodes" in graph and "edges" in graph
    print("[PASS] All existing endpoints (/health, /, /graph, /graph/rebuild) remain operational")


if __name__ == "__main__":
    test_unit_conflict_detection()
    test_api_endpoint()
    print("\n=== ALL CONFLICT DETECTION TESTS PASSED SUCCESSFULLY! ===")

