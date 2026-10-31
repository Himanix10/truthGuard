import urllib.request
import urllib.error
import json
import uuid
from pathlib import Path
import pymupdf as fitz

BASE_URL = "http://127.0.0.1:8000"

def upload_file(filepath: str, filename: str):
    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
    with open(filepath, "rb") as f:
        file_bytes = f.read()
    
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    
    req = urllib.request.Request(
        f"{BASE_URL}/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def extract_text(payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/extract",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def run_tests():
    print("Testing TruthGuard Document Text Extraction...")

    # 1. Health check
    req = urllib.request.Request(f"{BASE_URL}/health")
    with urllib.request.urlopen(req) as resp:
        health = json.loads(resp.read().decode())
    assert health["status"] == "healthy", f"Health check failed: {health}"
    print("[PASS] Health check passed")

    # 2. Upload and extract TXT file
    test_txt_path = Path("test_sample.txt")
    test_txt_path.write_text("TruthGuard temporal record: Claim verified on 2024-03-01. Special chars: accented e and symbols.", encoding="utf-8")

    up_txt = upload_file(str(test_txt_path), "temporal_sample.txt")
    print("Uploaded TXT:", up_txt["saved_filename"])
    assert up_txt["status"] == "success"
    txt_saved = up_txt["saved_filename"]

    status, ext_txt = extract_text({"saved_filename": txt_saved})
    print("Extracted TXT status:", ext_txt["extraction_status"], "char_count:", ext_txt["character_count"])
    assert status == 200
    assert ext_txt["extraction_status"] == "success"
    assert "TruthGuard temporal record" in ext_txt["extracted_text"]
    assert ext_txt["character_count"] == len(test_txt_path.read_text(encoding="utf-8"))
    assert ext_txt["original_filename"] == "temporal_sample.txt"
    print("[PASS] TXT extraction passed (UTF-8 preserved)")

    # 3. Create, upload and extract PDF file
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "TruthGuard Chronos Sample Verification Report: Event happened on 2024-05-10.")
    doc.save("test_doc.pdf")
    doc.close()

    up_pdf = upload_file("test_doc.pdf", "report_doc.pdf")
    print("Uploaded PDF:", up_pdf["saved_filename"])
    assert up_pdf["status"] == "success"
    pdf_saved = up_pdf["saved_filename"]

    status, ext_pdf = extract_text({"saved_filename": pdf_saved})
    print("Extracted PDF status:", ext_pdf["extraction_status"], "char_count:", ext_pdf["character_count"])
    assert status == 200
    assert ext_pdf["extraction_status"] == "success"
    assert "TruthGuard Chronos Sample Verification Report" in ext_pdf["extracted_text"]
    assert ext_pdf["character_count"] > 0
    assert ext_pdf["original_filename"] == "report_doc.pdf"
    print("[PASS] PDF extraction passed (PyMuPDF)")

    # 4. Create, upload and extract Blank/Scanned PDF (No text)
    doc_empty = fitz.open()
    doc_empty.new_page()
    doc_empty.save("test_blank.pdf")
    doc_empty.close()

    up_blank = upload_file("test_blank.pdf", "scanned_image.pdf")
    blank_saved = up_blank["saved_filename"]
    status, ext_blank = extract_text({"saved_filename": blank_saved})
    print("Extracted Blank PDF status:", ext_blank["extraction_status"], "msg:", ext_blank["message"])
    assert status == 200
    assert ext_blank["extraction_status"] == "no_text_found"
    assert ext_blank["character_count"] == 0
    assert "OCR is not supported yet" in ext_blank["message"]
    print("[PASS] Empty/Scanned PDF graceful handling passed")

    # 5. Path traversal tests
    status, err1 = extract_text({"saved_filename": "../../main.py"})
    print("Path traversal ../ result:", status)
    assert status == 400

    status, err2 = extract_text({"saved_filename": "..\\main.py"})
    print("Path traversal ..\\ result:", status)
    assert status == 400

    status, err3 = extract_text({"saved_filename": "non_existent_123.pdf"})
    print("Non-existent file result:", status)
    assert status == 404
    print("[PASS] Path traversal and security validations passed")

    # 6. Test with alternative key 'filename'
    status, ext_alt = extract_text({"filename": txt_saved})
    assert status == 200
    assert ext_alt["extraction_status"] == "success"
    print("[PASS] Alternative payload key 'filename' passed")

    # Cleanup local test generator files
    for p in [Path("test_sample.txt"), Path("test_doc.pdf"), Path("test_blank.pdf")]:
        if p.exists():
            p.unlink()

    print("\n==========================================")
    print("ALL VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("==========================================")

if __name__ == "__main__":
    run_tests()
