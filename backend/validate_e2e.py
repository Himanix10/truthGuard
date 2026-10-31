"""
TruthGuard-Chronos Final End-to-End Validation
"""

import json
import urllib.request
import urllib.error
from pathlib import Path

BACKEND_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://127.0.0.1:3000"
SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_documents"

def post_json(url, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_json(url):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def upload_file(url, file_path):
    boundary = "----WebKitFormBoundaryTruthGuardValidation"
    path = Path(file_path)
    with open(path, "rb") as f:
        file_bytes = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    print("=" * 75)
    print(" TRUTHGUARD-CHRONOS: FINAL END-TO-END VALIDATION REPORT")
    print("=" * 75)

    # 1. System availability
    print("\n[Check 1] System Availability & Startup")
    b_health = get_json(f"{BACKEND_URL}/health")
    print(f"  Backend ({BACKEND_URL}/health): {b_health}")
    
    with urllib.request.urlopen(FRONTEND_URL, timeout=10) as resp:
        fe_code = resp.status
        fe_html = resp.read().decode("utf-8")
    print(f"  Frontend ({FRONTEND_URL}): HTTP {fe_code}")
    print(f"  Frontend includes 'Temporal-Provenance Conflict Graph': {'Temporal-Provenance Conflict Graph' in fe_html}")
    print(f"  Frontend includes 'Try Demo Questions': {'Try Demo Questions' in fe_html}")

    # 2. Upload Sample PDFs
    print("\n[Check 2] Sample Document Uploads (POST /upload)")
    sample_files = [
        "CircularsOfficeOrders-065239f31ad7296-87408769.pdf",
        "Rule_10_Clarification.pdf",
        "TA_order_dated_18_08_2017_1.pdf"
    ]
    uploaded_files = {}
    for filename in sample_files:
        filepath = SAMPLE_DIR / filename
        up_res = upload_file(f"{BACKEND_URL}/upload", filepath)
        saved_name = up_res.get("saved_filename")
        uploaded_files[filename] = saved_name
        print(f"  [OK] {filename} -> {saved_name}")

    # 3. Document Text Extraction (POST /extract)
    print("\n[Check 3] Document Text Extraction (POST /extract)")
    for orig_name, saved_name in uploaded_files.items():
        ext_res = post_json(f"{BACKEND_URL}/extract", {"saved_filename": saved_name})
        char_count = ext_res.get("character_count", 0)
        status = ext_res.get("extraction_status")
        msg = ext_res.get("message")
        print(f"  File: {orig_name}")
        print(f"    Status: {status} | Characters: {char_count}")
        if status != "success":
            print(f"    Note: {msg}")

    # 4. Document Metadata Extraction (POST /metadata)
    print("\n[Check 4] Document Metadata Extraction (POST /metadata)")
    for orig_name, saved_name in uploaded_files.items():
        meta_res = post_json(f"{BACKEND_URL}/metadata", {"saved_filename": saved_name})
        title = meta_res.get("document_title") or "None"
        eff_date = meta_res.get("effective_date") or meta_res.get("publication_or_issue_date") or "None"
        policy_id = meta_res.get("policy_or_document_identifier") or "None"
        print(f"  File: {orig_name}")
        print(f"    Title: {title} | Date: {eff_date} | ID: {policy_id}")

    # 5. Rebuild TPCG Graph (POST /graph/rebuild)
    print("\n[Check 5] Rebuild & Query TPCG (POST /graph/rebuild & GET /graph)")
    rebuild_res = post_json(f"{BACKEND_URL}/graph/rebuild", {})
    print(f"  Rebuild Response: {rebuild_res.get('nodes_count')} nodes, {rebuild_res.get('edges_count')} edges")
    graph_data = get_json(f"{BACKEND_URL}/graph")
    print(f"  GET /graph: Verified {len(graph_data.get('nodes', []))} nodes, {len(graph_data.get('edges', []))} edges")

    # 6. Retrieve Evidence (POST /retrieve)
    print("\n[Check 6] Passage Retrieval (POST /retrieve)")
    q1 = "What are the rules for travel by Vande Bharat Express on official tour?"
    ret_res = post_json(f"{BACKEND_URL}/retrieve", {"question": q1, "top_k": 3})
    retrieved_passages = ret_res.get("retrieved_passages", [])
    print(f"  Query: '{q1}'")
    print(f"  Passages Retrieved: {len(retrieved_passages)}")
    for i, p in enumerate(retrieved_passages[:2], 1):
        source = p.get("original_filename") or p.get("filename")
        score = p.get("relevance_score", 0.0)
        snippet = p.get("snippet", "")[:110].replace("\n", " ")
        print(f"    [{i}] (Score: {score:.3f}, Doc: {source}): \"{snippet}...\"")

    # 7. End-to-End POST /ask with Vande Bharat Travel
    print("\n[Check 7] End-to-End Workflow: Vande Bharat Travel (POST /ask)")
    ask_res1 = post_json(f"{BACKEND_URL}/ask", {"question": q1, "top_k": 5})
    outcome1 = ask_res1.get("outcome")
    citations1 = ask_res1.get("citations", [])
    critic1 = ask_res1.get("critic_status")
    ans1 = ask_res1.get("final_answer", "")
    print(f"  Outcome: {outcome1}")
    print(f"  Critic Status: {critic1}")
    print(f"  Citations Count: {len(citations1)}")
    for c in citations1:
        print(f"    - Citation [{c.get('citation_id')}]: {c.get('filename')} (Date: {c.get('effective_or_issue_date')})")
    print(f"  Explanation: {ask_res1.get('explanation')}")
    print(f"  Answer Preview:\n    {ans1[:240]}...")

    # 8. End-to-End POST /ask with Unrelated / Missing Evidence Question
    print("\n[Check 8] End-to-End Workflow: Unrelated Evidence Question (POST /ask)")
    q2 = "What is the procedure for subatomic warp drive teleportation?"
    ask_res2 = post_json(f"{BACKEND_URL}/ask", {"question": q2, "top_k": 5})
    outcome2 = ask_res2.get("outcome")
    abstention2 = ask_res2.get("abstention_reason")
    ans2 = ask_res2.get("final_answer")
    print(f"  Query: '{q2}'")
    print(f"  Outcome: {outcome2}")
    print(f"  Abstention Reason: {abstention2}")
    print(f"  Final Answer: {ans2 if ans2 else '(Empty - system abstained from inventing)'}")

    print("\n" + "=" * 75)
    print(" VERIFICATION COMPLETE")
    print("=" * 75)

if __name__ == "__main__":
    main()
