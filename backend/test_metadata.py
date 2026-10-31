import urllib.request
import urllib.error
import json
import uuid
from pathlib import Path
import pymupdf as fitz

BASE_URL = "http://127.0.0.1:8000"

def upload_bytes(file_bytes: bytes, filename: str):
    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"{BASE_URL}/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def post_metadata(payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/metadata",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def run_tests():
    print("Running Document Metadata Extraction Tests...")

    # Test 1: Full Corporate Policy Document (TXT)
    sample_policy = (
        "Global Information Security Policy\n"
        "Policy ID: POL-SEC-2025-009\n"
        "Version: 3.2\n"
        "Effective Date: 2025-02-01\n"
        "Issue Date: 2025-01-15\n"
        "Scope: Global\n\n"
        "1. Purpose\n"
        "This policy supersedes POL-SEC-2022-001 and replaces Security Standard STD-04.\n"
        "All corporate assets must adhere to established encryption rules."
    )
    up1 = upload_bytes(sample_policy.encode("utf-8"), "sec_policy.txt")
    print("Uploaded Sample Policy:", up1["saved_filename"])
    assert up1["status"] == "success"

    status, meta1 = post_metadata({"saved_filename": up1["saved_filename"]})
    print("Metadata Output 1:", json.dumps(meta1["metadata"], indent=2))
    assert status == 200
    assert meta1["metadata"]["document_title"] == "Global Information Security Policy"
    assert meta1["metadata"]["policy_or_document_identifier"] == "POL-SEC-2025-009"
    assert meta1["metadata"]["version_number"] == "3.2"
    assert meta1["metadata"]["effective_date"] == "2025-02-01"
    assert meta1["metadata"]["publication_or_issue_date"] == "2025-01-15"
    assert meta1["metadata"]["geographic_or_organizational_scope"] == "Global"
    assert meta1["metadata"]["appears_amendment_or_replacement"] is True
    assert meta1["metadata"]["referenced_parent_or_previous_policy_identifier"] == "POL-SEC-2022-001"
    print("[PASS] Full policy metadata extracted accurately")

    # Test 2: Minimal Document (Tests non-hallucination / returning null)
    minimal_doc = "Team Sync Notes\nDiscussed frontend tasks and backend endpoints."
    up2 = upload_bytes(minimal_doc.encode("utf-8"), "meeting.txt")
    status, meta2 = post_metadata({"saved_filename": up2["saved_filename"]})
    assert status == 200
    assert meta2["metadata"]["document_title"] == "Team Sync Notes"
    assert meta2["metadata"]["effective_date"] is None
    assert meta2["metadata"]["publication_or_issue_date"] is None
    assert meta2["metadata"]["version_number"] is None
    assert meta2["metadata"]["policy_or_document_identifier"] is None
    assert meta2["metadata"]["geographic_or_organizational_scope"] is None
    assert meta2["metadata"]["appears_amendment_or_replacement"] is False
    assert meta2["metadata"]["referenced_parent_or_previous_policy_identifier"] is None
    print("[PASS] Non-hallucination rule verified: unidentified fields return null")

    # Test 3: PDF Document with Scope & Amendment
    pdf_doc = fitz.open()
    page = pdf_doc.new_page()
    page.insert_text(
        (50, 50),
        "Document Title: APAC Regional Data Governance\n"
        "Doc ID: DG-APAC-042\n"
        "Revision: v1.0\n"
        "Scope: Regional (APAC)\n"
        "Published Date: October 15, 2026\n"
        "Effective as of: November 1, 2026\n"
        "This policy amends DG-GLOBAL-001.\n"
    )
    pdf_bytes = pdf_doc.write()
    pdf_doc.close()

    up3 = upload_bytes(pdf_bytes, "apac_governance.pdf")
    status, meta3 = post_metadata({"saved_filename": up3["saved_filename"]})
    assert status == 200
    assert meta3["metadata"]["document_title"] == "APAC Regional Data Governance"
    assert meta3["metadata"]["policy_or_document_identifier"] == "DG-APAC-042"
    assert meta3["metadata"]["version_number"] == "v1.0"
    assert meta3["metadata"]["geographic_or_organizational_scope"] == "Regional (APAC)"
    assert meta3["metadata"]["appears_amendment_or_replacement"] is True
    assert meta3["metadata"]["referenced_parent_or_previous_policy_identifier"] == "DG-GLOBAL-001"
    print("[PASS] PDF metadata extraction verified")

    # Test 4: Blank PDF (No text)
    blank_pdf = fitz.open()
    blank_pdf.new_page()
    blank_bytes = blank_pdf.write()
    blank_pdf.close()

    up4 = upload_bytes(blank_bytes, "blank.pdf")
    status, meta4 = post_metadata({"saved_filename": up4["saved_filename"]})
    assert status == 200
    assert meta4["extraction_status"] == "no_text_found"
    assert meta4["metadata"]["document_title"] is None
    print("[PASS] Blank/Scanned PDF gracefully handled")

    # Test 5: Security / Path Traversal
    status, err1 = post_metadata({"saved_filename": "../../main.py"})
    assert status == 400
    status, err2 = post_metadata({"saved_filename": "..\\main.py"})
    assert status == 400
    status, err3 = post_metadata({"saved_filename": "nonexistent_file.pdf"})
    assert status == 404
    print("[PASS] Security and path traversal protections verified")

    print("\n==========================================")
    print("ALL METADATA EXTRACTION TESTS PASSED!")
    print("==========================================")

if __name__ == "__main__":
    run_tests()
