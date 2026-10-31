"""
Unit and Integration Tests for Temporal-Provenance Conflict Graph (TPCG).
Tests graph node creation, relationship inference, queries, and FastAPI endpoints.
"""

import sys
import json
from pathlib import Path

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from tpcg import TemporalProvenanceConflictGraph, to_json_safe
from metadata_extractor import DocumentMetadata
import main


def test_unit_tpcg():
    print("--- 1. Testing TPCG Unit Logic & Relationship Inference ---")
    tpcg = TemporalProvenanceConflictGraph()

    # Document 1: Original Security Policy
    tpcg.add_document_node(
        saved_filename="01_sec_v1.txt",
        original_filename="sec_policy_v1.txt",
        metadata={
            "document_title": "Information Security Standard",
            "effective_date": "2022-01-01",
            "publication_or_issue_date": "2021-12-15",
            "version_number": "1.0",
            "policy_or_document_identifier": "POL-SEC-2022-001",
            "geographic_or_organizational_scope": "Global",
            "appears_amendment_or_replacement": False,
            "referenced_parent_or_previous_policy_identifier": None,
        },
        raw_text="Information Security Standard\nPolicy ID: POL-SEC-2022-001\nVersion: 1.0\nScope: Global",
    )

    # Document 2: Superseding Policy
    tpcg.add_document_node(
        saved_filename="02_sec_v2.txt",
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
        raw_text="Information Security Standard\nPolicy ID: POL-SEC-2025-009\nVersion: 2.0\nThis policy supersedes POL-SEC-2022-001.",
    )

    # Document 3: Global Data Governance
    tpcg.add_document_node(
        saved_filename="03_data_gov.txt",
        original_filename="data_governance.txt",
        metadata={
            "document_title": "Global Data Governance Policy",
            "effective_date": "2024-06-01",
            "publication_or_issue_date": "2024-05-15",
            "version_number": "1.0",
            "policy_or_document_identifier": "DG-GLOBAL-001",
            "geographic_or_organizational_scope": "Global",
            "appears_amendment_or_replacement": False,
            "referenced_parent_or_previous_policy_identifier": None,
        },
        raw_text="Global Data Governance Policy\nDoc ID: DG-GLOBAL-001\nVersion: 1.0",
    )

    # Document 4: Amending Regional Policy
    tpcg.add_document_node(
        saved_filename="04_apac_gov.txt",
        original_filename="apac_governance.txt",
        metadata={
            "document_title": "APAC Data Governance Addendum",
            "effective_date": "2026-11-01",
            "publication_or_issue_date": "2026-10-15",
            "version_number": "1.1",
            "policy_or_document_identifier": "DG-APAC-042",
            "geographic_or_organizational_scope": "Regional (APAC)",
            "appears_amendment_or_replacement": True,
            "referenced_parent_or_previous_policy_identifier": "DG-GLOBAL-001",
        },
        raw_text="APAC Data Governance Addendum\nDoc ID: DG-APAC-042\nThis policy amends DG-GLOBAL-001.",
    )

    # Document 5 & 6: SAME_POLICY (same policy identifier, different versions)
    tpcg.add_document_node(
        saved_filename="05_ops_v1.txt",
        original_filename="ops_procedure_v1.txt",
        metadata={
            "document_title": "Standard Operating Procedure",
            "effective_date": "2023-01-01",
            "publication_or_issue_date": "2022-12-01",
            "version_number": "1.0",
            "policy_or_document_identifier": "SOP-OPS-100",
            "geographic_or_organizational_scope": "Operations",
            "appears_amendment_or_replacement": False,
            "referenced_parent_or_previous_policy_identifier": None,
        },
        raw_text="Standard Operating Procedure\nID: SOP-OPS-100\nVersion: 1.0",
    )
    tpcg.add_document_node(
        saved_filename="06_ops_v2.txt",
        original_filename="ops_procedure_v2.txt",
        metadata={
            "document_title": "Standard Operating Procedure",
            "effective_date": "2024-01-01",
            "publication_or_issue_date": "2023-12-01",
            "version_number": "2.0",
            "policy_or_document_identifier": "SOP-OPS-100",
            "geographic_or_organizational_scope": "Operations",
            "appears_amendment_or_replacement": False,
            "referenced_parent_or_previous_policy_identifier": None,
        },
        raw_text="Standard Operating Procedure\nID: SOP-OPS-100\nVersion: 2.0",
    )

    # Document 7: RELATED_TO (references parent policy without amending/superseding)
    tpcg.add_document_node(
        saved_filename="07_hr_guideline.txt",
        original_filename="hr_guidelines.txt",
        metadata={
            "document_title": "Remote Work Guidelines",
            "effective_date": "2025-05-01",
            "publication_or_issue_date": "2025-04-15",
            "version_number": "1.0",
            "policy_or_document_identifier": "GL-HR-005",
            "geographic_or_organizational_scope": "HR",
            "appears_amendment_or_replacement": False,
            "referenced_parent_or_previous_policy_identifier": "POL-SEC-2022-001",
        },
        raw_text="Remote Work Guidelines\nID: GL-HR-005\nParent Policy: POL-SEC-2022-001\nFollow all standard security controls.",
    )

    # Document 8: Unrelated document with missing metadata (Non-hallucination verification)
    tpcg.add_document_node(
        saved_filename="08_notes.txt",
        original_filename="meeting_notes.txt",
        metadata={
            "document_title": "Weekly Team Meeting",
            "effective_date": None,
            "publication_or_issue_date": None,
            "version_number": None,
            "policy_or_document_identifier": None,
            "geographic_or_organizational_scope": None,
            "appears_amendment_or_replacement": False,
            "referenced_parent_or_previous_policy_identifier": None,
        },
        raw_text="Weekly Team Meeting\nNotes on sprint tasks and general announcements.",
    )

    # Infer relationships
    tpcg.infer_relationships()

    print(f"Nodes in graph: {tpcg.node_count}")
    print(f"Edges in graph: {tpcg.edge_count}")
    assert tpcg.node_count == 8, f"Expected 8 nodes, got {tpcg.node_count}"

    # Verify SUPERSEDES edge: 02_sec_v2.txt -> 01_sec_v1.txt
    assert tpcg.graph.has_edge("02_sec_v2.txt", "01_sec_v1.txt"), "Missing SUPERSEDES edge from Doc 2 to Doc 1"
    edge_02_01 = tpcg.graph.get_edge_data("02_sec_v2.txt", "01_sec_v1.txt")
    assert edge_02_01["relationship"] == "SUPERSEDES"
    print("[PASS] SUPERSEDES edge verified successfully")

    # Verify AMENDS edge: 04_apac_gov.txt -> 03_data_gov.txt
    assert tpcg.graph.has_edge("04_apac_gov.txt", "03_data_gov.txt"), "Missing AMENDS edge from Doc 4 to Doc 3"
    edge_04_03 = tpcg.graph.get_edge_data("04_apac_gov.txt", "03_data_gov.txt")
    assert edge_04_03["relationship"] == "AMENDS"
    print("[PASS] AMENDS edge verified successfully")

    # Verify SAME_POLICY edge: 06_ops_v2.txt -> 05_ops_v1.txt
    assert tpcg.graph.has_edge("06_ops_v2.txt", "05_ops_v1.txt"), "Missing SAME_POLICY edge between SOP versions"
    edge_06_05 = tpcg.graph.get_edge_data("06_ops_v2.txt", "05_ops_v1.txt")
    assert edge_06_05["relationship"] == "SAME_POLICY"
    print("[PASS] SAME_POLICY edge verified successfully")

    # Verify RELATED_TO edge: 07_hr_guideline.txt -> 01_sec_v1.txt
    assert tpcg.graph.has_edge("07_hr_guideline.txt", "01_sec_v1.txt"), "Missing RELATED_TO edge from Doc 7 to Doc 1"
    edge_07_01 = tpcg.graph.get_edge_data("07_hr_guideline.txt", "01_sec_v1.txt")
    assert edge_07_01["relationship"] == "RELATED_TO"
    print("[PASS] RELATED_TO edge verified successfully")

    # Verify Non-hallucination / Isolated node: 08_notes.txt
    assert tpcg.graph.degree("08_notes.txt") == 0, f"Expected 0 edges for isolated node, got {tpcg.graph.degree('08_notes.txt')}"
    print("[PASS] Non-hallucination verified: document with missing metadata has 0 edges")

    # Verify Node Attributes completeness
    node_data = tpcg.get_node("02_sec_v2.txt")
    required_keys = [
        "filename",
        "title",
        "effective_date",
        "issue_date",
        "version",
        "document_identifier",
        "scope",
        "amendment_status",
        "parent_policy_identifier",
    ]
    for key in required_keys:
        assert key in node_data, f"Required node attribute '{key}' missing from node"
    assert node_data["effective_date"] == "2025-02-01"
    assert node_data["document_identifier"] == "POL-SEC-2025-009"
    assert node_data["parent_policy_identifier"] == "POL-SEC-2022-001"
    assert node_data["amendment_status"] is True
    print("[PASS] All 9 required node metadata attributes confirmed present")

    # Verify JSON Serialization Safety
    graph_dict = tpcg.to_dict()
    json_str = json.dumps(graph_dict)
    reloaded = json.loads(json_str)
    assert len(reloaded["nodes"]) == 8
    assert len(reloaded["edges"]) >= 4
    print("[PASS] JSON serialization safety verified")

    # Verify Lineage and Query methods
    lineage = tpcg.get_policy_lineage("01_sec_v1.txt")
    assert len(lineage["predecessors"]) >= 2  # Doc 2 (SUPERSEDES) and Doc 7 (RELATED_TO) point to Doc 1
    found = tpcg.find_nodes_by_identifier("POL-SEC-2025-009")
    assert len(found) == 1 and found[0]["id"] == "02_sec_v2.txt"
    print("[PASS] Graph query functions (find_nodes_by_identifier, get_policy_lineage) verified")


def test_api_endpoints():
    print("\n--- 2. Testing FastAPI Graph Endpoints Directly ---")
    import io
    from fastapi.datastructures import UploadFile

    # Test /health
    health = main.health_check()
    assert health == {"status": "healthy"}
    print("[PASS] GET /health endpoint working")

    # Upload test document 1 (Parent policy)
    doc1_content = (
        b"Enterprise Data Governance Standard\n"
        b"Policy ID: POL-E2E-100\n"
        b"Version: 1.0\n"
        b"Effective Date: 2024-01-01\n"
        b"Scope: Global\n"
    )
    f1 = UploadFile(filename="e2e_gov_v1.txt", file=io.BytesIO(doc1_content))
    up1 = main.upload_file(f1)
    assert up1["status"] == "success"
    saved1 = up1["saved_filename"]

    # Upload test document 2 (Amending policy)
    doc2_content = (
        b"Enterprise Data Governance APAC Amendment\n"
        b"Policy ID: POL-E2E-101\n"
        b"Version: 1.1\n"
        b"Effective Date: 2025-01-01\n"
        b"Scope: Regional (APAC)\n"
        b"This policy amends POL-E2E-100.\n"
    )
    f2 = UploadFile(filename="e2e_gov_v2.txt", file=io.BytesIO(doc2_content))
    up2 = main.upload_file(f2)
    assert up2["status"] == "success"
    saved2 = up2["saved_filename"]

    # Upload test document 3 (Related document)
    doc3_content = (
        b"Enterprise Data Retention Schedule\n"
        b"Policy ID: POL-E2E-102\n"
        b"Version: 1.0\n"
        b"Parent Policy: POL-E2E-100\n"
        b"Scope: Global\n"
    )
    f3 = UploadFile(filename="e2e_retention.txt", file=io.BytesIO(doc3_content))
    up3 = main.upload_file(f3)
    assert up3["status"] == "success"
    saved3 = up3["saved_filename"]

    try:
        # Test /metadata endpoint on newly uploaded doc
        meta_res = main.extract_metadata(filename=saved2)
        assert meta_res["extraction_status"] == "success"
        assert meta_res["document_title"] == "Enterprise Data Governance APAC Amendment"
        assert meta_res["policy_or_document_identifier"] == "POL-E2E-101"
        assert meta_res["appears_amendment_or_replacement"] is True
        print("[PASS] POST /metadata endpoint functioning correctly")

        # Test POST /graph/rebuild
        rebuild_res = main.rebuild_graph()
        assert rebuild_res["status"] == "success"
        assert rebuild_res["nodes_count"] >= 3
        print(f"[PASS] POST /graph/rebuild succeeded: {rebuild_res['nodes_count']} nodes, {rebuild_res['edges_count']} edges")

        # Test GET /graph
        graph_res = main.get_graph()
        assert "nodes" in graph_res
        assert "edges" in graph_res
        assert "nodes_count" in graph_res
        assert "edges_count" in graph_res
        print(f"[PASS] GET /graph succeeded: {graph_res['nodes_count']} nodes, {graph_res['edges_count']} edges")

        # Verify edge between saved2 and saved1 (AMENDS)
        edges = graph_res["edges"]
        amends_edges = [e for e in edges if e["source"] == saved2 and e["target"] == saved1]
        assert len(amends_edges) == 1, f"Expected AMENDS edge between {saved2} and {saved1}"
        assert amends_edges[0]["relationship"] == "AMENDS"
        print("[PASS] Rebuilt graph contains inferred AMENDS edge between uploaded documents")

        # Verify edge between saved3 and saved1 (RELATED_TO)
        related_edges = [e for e in edges if e["source"] == saved3 and e["target"] == saved1]
        assert len(related_edges) == 1, f"Expected RELATED_TO edge between {saved3} and {saved1}"
        assert related_edges[0]["relationship"] == "RELATED_TO"
        print("[PASS] Rebuilt graph contains inferred RELATED_TO edge between uploaded documents")

        # Inspect required node attributes
        sample_node = next(n for n in graph_res["nodes"] if n["id"] == saved2)
        required_keys = [
            "filename",
            "title",
            "effective_date",
            "issue_date",
            "version",
            "document_identifier",
            "scope",
            "amendment_status",
            "parent_policy_identifier",
        ]
        for k in required_keys:
            assert k in sample_node, f"Missing key '{k}' in GET /graph node response"
        print("[PASS] GET /graph returns all required metadata attributes")

    finally:
        # Clean up temporary test files
        for s_name in (saved1, saved2, saved3):
            p = main.UPLOAD_DIR / s_name
            if p.exists():
                p.unlink()


if __name__ == "__main__":
    test_unit_tpcg()
    test_api_endpoints()
    print("\n=== ALL TPCG TESTS PASSED SUCCESSFULLY! ===")
