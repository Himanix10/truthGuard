import shutil
import uuid
import re
from pathlib import Path
from typing import Optional, List
import pymupdf as fitz
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Body, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from metadata_extractor import extract_document_metadata, DocumentMetadata
from tpcg import TemporalProvenanceConflictGraph
from conflict_detector import ConflictDetector
from comparator import compare_two_documents, CompareRequest
from retriever_agent import RetrieverChronoAnnotatorAgent
from synthesizer_agent import SynthesizerAgent
from critic_agent import CriticAgent
from arbitration_agent import ArbitrationAgent
from orchestrator import OrchestratorWorkflow

app = FastAPI(title="TruthGuard-Chronos API")

# Initialize in-memory Temporal-Provenance Conflict Graph (TPCG)
tpcg_graph = TemporalProvenanceConflictGraph()

# Configure CORS to allow local Next.js frontend on port 3000, 3001, or any local port
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure upload directory exists inside backend/uploads/
UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".txt"}


class ExtractRequest(BaseModel):
    saved_filename: Optional[str] = Field(
        default=None,
        description="The unique saved filename returned by the /upload endpoint",
    )
    filename: Optional[str] = Field(
        default=None,
        description="Alternative key for the saved filename",
    )


class MetadataRequest(BaseModel):
    saved_filename: Optional[str] = Field(
        default=None,
        description="The unique saved filename returned by the /upload endpoint",
    )
    filename: Optional[str] = Field(
        default=None,
        description="Alternative key for the saved filename",
    )


def validate_and_resolve_filename(filename: str, base_dir: Path) -> Path:
    """
    Validates the filename to prevent directory traversal and checks file existence in base_dir.
    Accepts either the saved filename or a full/relative path pointing inside backend/uploads.
    """
    if not filename or not isinstance(filename, str):
        raise HTTPException(
            status_code=400,
            detail="Filename is required.",
        )

    clean_name = filename.strip().strip("'\"")
    if not clean_name:
        raise HTTPException(
            status_code=400,
            detail="Filename cannot be empty.",
        )

    if "\0" in clean_name:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename: Null bytes are not permitted.",
        )

    base_resolved = base_dir.resolve()
    path_candidate = Path(clean_name)

    # Disallow explicit traversal
    if ".." in clean_name:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename: Directory traversal ('..') is not permitted.",
        )

    if path_candidate.is_absolute():
        target_path = path_candidate.resolve()
    elif "/" in clean_name or "\\" in clean_name:
        target_path = (base_dir / path_candidate.name).resolve()
    else:
        target_path = (base_dir / clean_name).resolve()

    # Ensure resolved path is strictly within base_dir
    try:
        target_path.relative_to(base_resolved)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Access denied: File must reside inside the backend/uploads directory.",
        )

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"File '{target_path.name}' not found in uploads directory.",
        )

    return target_path


def get_original_filename(saved_filename: str) -> str:
    """
    Extracts the original filename from the unique prefix_filename pattern.
    """
    if "_" in saved_filename:
        prefix, remainder = saved_filename.split("_", 1)
        if len(prefix) == 8 and all(c in "0123456789abcdefABCDEF" for c in prefix):
            return remainder
    return saved_filename


def extract_text_from_pdf(file_path: Path) -> str:
    """
    Extracts text from a PDF file using PyMuPDF (fitz).
    """
    try:
        doc = fitz.open(file_path)
    except Exception as e:
        if file_path.stat().st_size == 0:
            return ""
        raise HTTPException(
            status_code=400,
            detail=f"Unable to parse PDF document: {str(e)}",
        )

    try:
        if len(doc) == 0:
            return ""

        extracted_pages = []
        for page in doc:
            extracted_pages.append(page.get_text())
        return "".join(extracted_pages)
    finally:
        doc.close()


def extract_text_from_txt(file_path: Path) -> str:
    """
    Extracts text from a TXT file using UTF-8, gracefully handling decoding errors.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read TXT file: {str(e)}",
        )


def get_extracted_content_for_file(filename_str: str, base_dir: Path):
    """
    Validates the file path and extracts text using existing extraction logic.
    """
    target_path = validate_and_resolve_filename(filename_str, base_dir)
    ext = target_path.suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{ext}'. Only PDF (.pdf) and TXT (.txt) files can be processed.",
        )

    original_filename = get_original_filename(target_path.name)

    if ext == ".pdf":
        extracted_text = extract_text_from_pdf(target_path)
    elif ext == ".txt":
        extracted_text = extract_text_from_txt(target_path)
    else:
        extracted_text = ""

    return {
        "target_path": target_path,
        "original_filename": original_filename,
        "ext": ext,
        "extracted_text": extracted_text,
    }


@app.get("/")
def read_root():
    return {"message": "TruthGuard-Chronos API is running"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/upload")
def upload_file(file: UploadFile = File(...)):
    """
    Accepts PDF and TXT files, validates format, and saves with a unique name.
    """
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No filename provided in upload request.",
        )

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{ext}'. Only PDF (.pdf) and TXT (.txt) files are accepted.",
        )

    try:
        # Sanitize original name and generate unique filename
        safe_original = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", Path(file.filename).name)
        unique_prefix = uuid.uuid4().hex[:8]
        saved_filename = f"{unique_prefix}_{safe_original}"
        saved_path = UPLOAD_DIR / saved_filename

        with open(saved_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Ingest uploaded file into in-memory TPCG graph
        try:
            content_result = get_extracted_content_for_file(saved_filename, UPLOAD_DIR)
            extracted_text = content_result.get("extracted_text", "")
            metadata = extract_document_metadata(extracted_text, file.filename)
            tpcg_graph.add_document_node(
                saved_filename=saved_filename,
                original_filename=file.filename,
                metadata=metadata,
                raw_text=extracted_text,
            )
            tpcg_graph.infer_relationships()
        except Exception:
            pass

        return {
            "status": "success",
            "message": "File uploaded successfully.",
            "original_filename": file.filename,
            "saved_filename": saved_filename,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save file: {str(e)}",
        )
    finally:
        file.file.close()


@app.post("/extract")
def extract_text(
    payload: Optional[ExtractRequest] = Body(default=None),
    saved_filename: Optional[str] = Query(None),
    filename: Optional[str] = Query(None),
):
    """
    Extracts text from an uploaded document in the backend/uploads directory.
    Supports PDF (via PyMuPDF) and TXT (via UTF-8 with fallback error replacement).
    """
    target_name = (
        (payload.saved_filename if isinstance(payload, (MetadataRequest, ExtractRequest)) and payload.saved_filename else None)
        or (payload.filename if isinstance(payload, (MetadataRequest, ExtractRequest)) and payload.filename else None)
        or (saved_filename if isinstance(saved_filename, str) and saved_filename else None)
        or (filename if isinstance(filename, str) and filename else None)
    )

    if not target_name:
        raise HTTPException(
            status_code=400,
            detail="Missing filename. Provide 'saved_filename' or 'filename' in the request body.",
        )

    result = get_extracted_content_for_file(target_name, UPLOAD_DIR)
    target_path = result["target_path"]
    original_filename = result["original_filename"]
    extracted_text = result["extracted_text"]
    ext = result["ext"]

    if ext == ".pdf":
        if not extracted_text.strip():
            return {
                "original_filename": original_filename,
                "saved_filename": target_path.name,
                "extracted_text": "",
                "character_count": 0,
                "extraction_status": "no_text_found",
                "message": "No extractable text found in PDF. Scanned or image-only documents are not supported yet (OCR is not supported yet).",
            }
        return {
            "original_filename": original_filename,
            "saved_filename": target_path.name,
            "extracted_text": extracted_text,
            "character_count": len(extracted_text),
            "extraction_status": "success",
            "message": "Text extracted successfully.",
        }

    elif ext == ".txt":
        if not extracted_text.strip():
            return {
                "original_filename": original_filename,
                "saved_filename": target_path.name,
                "extracted_text": "",
                "character_count": 0,
                "extraction_status": "empty",
                "message": "The text file is empty.",
            }
        return {
            "original_filename": original_filename,
            "saved_filename": target_path.name,
            "extracted_text": extracted_text,
            "character_count": len(extracted_text),
            "extraction_status": "success",
            "message": "Text extracted successfully.",
        }


@app.post("/metadata")
def extract_metadata(
    payload: Optional[MetadataRequest] = Body(default=None),
    saved_filename: Optional[str] = Query(None),
    filename: Optional[str] = Query(None),
):
    """
    Extracts structured document metadata (title, dates, version, identifiers, scope, amendments)
    from an uploaded document in the backend/uploads directory using rule-based/regex extraction.
    """
    target_name = (
        (payload.saved_filename if isinstance(payload, (MetadataRequest, ExtractRequest)) and payload.saved_filename else None)
        or (payload.filename if isinstance(payload, (MetadataRequest, ExtractRequest)) and payload.filename else None)
        or (saved_filename if isinstance(saved_filename, str) and saved_filename else None)
        or (filename if isinstance(filename, str) and filename else None)
    )

    if not target_name:
        raise HTTPException(
            status_code=400,
            detail="Missing filename. Provide 'saved_filename' or 'filename' in the request body.",
        )

    result = get_extracted_content_for_file(target_name, UPLOAD_DIR)
    target_path = result["target_path"]
    original_filename = result["original_filename"]
    extracted_text = result["extracted_text"]

    if not extracted_text.strip():
        empty_meta = DocumentMetadata()
        meta_dict = empty_meta.model_dump()
        return {
            "saved_filename": target_path.name,
            "original_filename": original_filename,
            "extraction_status": "no_text_found",
            "message": "No extractable text found in document. Scanned or image-only documents are not supported yet (OCR is not supported yet).",
            "metadata": meta_dict,
            "document_title": None,
            "effective_date": None,
            "publication_or_issue_date": None,
            "version_number": None,
            "policy_or_document_identifier": None,
            "geographic_or_organizational_scope": None,
            "appears_amendment_or_replacement": False,
            "referenced_parent_or_previous_policy_identifier": None,
        }

    metadata = extract_document_metadata(extracted_text, original_filename)
    meta_dict = metadata.model_dump()

    return {
        "saved_filename": target_path.name,
        "original_filename": original_filename,
        "extraction_status": "success",
        "message": "Metadata extracted successfully.",
        "metadata": meta_dict,
        "document_title": meta_dict["document_title"],
        "effective_date": meta_dict["effective_date"],
        "publication_or_issue_date": meta_dict["publication_or_issue_date"],
        "version_number": meta_dict["version_number"],
        "policy_or_document_identifier": meta_dict["policy_or_document_identifier"],
        "geographic_or_organizational_scope": meta_dict["geographic_or_organizational_scope"],
        "appears_amendment_or_replacement": meta_dict["appears_amendment_or_replacement"],
        "referenced_parent_or_previous_policy_identifier": meta_dict["referenced_parent_or_previous_policy_identifier"],
    }


class GraphRebuildRequest(BaseModel):
    files: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific filenames in backend/uploads to include in the graph.",
    )


@app.on_event("startup")
def startup_populate_graph():
    """Initializes in-memory TPCG graph from existing uploads on application startup."""
    try:
        if any(UPLOAD_DIR.glob("*.*")):
            tpcg_graph.build_from_directory(UPLOAD_DIR)
    except Exception:
        pass


@app.post("/graph/rebuild")
def rebuild_graph(payload: Optional[GraphRebuildRequest] = Body(default=None)):
    """
    Rebuilds the Temporal-Provenance Conflict Graph (TPCG) in memory using
    the uploaded documents and their extracted metadata.
    """
    try:
        graph_data = tpcg_graph.build_from_directory(UPLOAD_DIR)
        return {
            "status": "success",
            "message": "Graph rebuilt successfully using uploaded documents and extracted metadata.",
            "nodes_count": graph_data["node_count"],
            "edges_count": graph_data["edge_count"],
            "nodes": graph_data["nodes"],
            "edges": graph_data["edges"],
            "graph": graph_data,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to rebuild graph: {str(e)}",
        )


@app.get("/graph")
def get_graph():
    """
    Returns the JSON representation of graph nodes and edges from the
    in-memory Temporal-Provenance Conflict Graph (TPCG).
    """
    # Lazily populate if empty but files are present
    if tpcg_graph.node_count == 0 and any(UPLOAD_DIR.glob("*.*")):
        tpcg_graph.build_from_directory(UPLOAD_DIR)

    graph_data = tpcg_graph.to_dict()
    return {
        "nodes": graph_data["nodes"],
        "edges": graph_data["edges"],
        "nodes_count": graph_data["node_count"],
        "edges_count": graph_data["edge_count"],
    }


class ConflictDetectRequest(BaseModel):
    files: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific filenames in backend/uploads to detect conflicts among.",
    )


@app.post("/conflicts/detect")
def detect_conflicts(payload: Optional[ConflictDetectRequest] = Body(default=None)):
    """
    Detects and classifies potential policy conflicts between documents using
    the Temporal-Provenance Conflict Graph (TPCG) and document metadata.
    Classifies into: supersession, scope_conflict, temporal_conflict, insufficient_evidence.
    """
    # Lazily populate if empty but files are present
    if tpcg_graph.node_count == 0 and any(UPLOAD_DIR.glob("*.*")):
        tpcg_graph.build_from_directory(UPLOAD_DIR)

    target_files = (
        payload.files
        if isinstance(payload, ConflictDetectRequest) and payload.files
        else None
    )

    detector = ConflictDetector(graph=tpcg_graph)
    conflicts = detector.detect_conflicts(target_files=target_files)

    summary = {
        "supersession": sum(1 for c in conflicts if c.get("conflict_type") == "supersession"),
        "scope_conflict": sum(1 for c in conflicts if c.get("conflict_type") == "scope_conflict"),
        "temporal_conflict": sum(1 for c in conflicts if c.get("conflict_type") == "temporal_conflict"),
        "insufficient_evidence": sum(1 for c in conflicts if c.get("conflict_type") == "insufficient_evidence"),
    }

    return {
        "status": "success",
        "conflicts_count": len(conflicts),
        "conflicts": conflicts,
        "summary": summary,
    }


class RetrieveRequest(BaseModel):
    question: str = Field(
        ...,
        description="The user question or query to retrieve policy passages for",
    )
    top_k: Optional[int] = Field(
        default=5,
        description="Maximum number of passages to return (default: 5)",
    )
    files: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific filenames in backend/uploads to restrict retrieval to",
    )


@app.post("/retrieve")
def retrieve_passages(payload: RetrieveRequest = Body(...)):
    """
    Executes the LangGraph Retriever & Chrono-Annotator Agent workflow to retrieve
    relevant contextual passages from uploaded documents and annotate them with
    temporal and provenance metadata.
    """
    if not payload or not payload.question or not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    # Lazily populate if empty but files are present
    if tpcg_graph.node_count == 0 and any(UPLOAD_DIR.glob("*.*")):
        tpcg_graph.build_from_directory(UPLOAD_DIR)

    agent = RetrieverChronoAnnotatorAgent(tpcg=tpcg_graph, upload_dir=UPLOAD_DIR)
    result = agent.run(
        question=payload.question,
        top_k=payload.top_k or 5,
        filter_files=payload.files,
    )

    return {
        "status": "success",
        "question": result["question"],
        "passages_count": result["passages_count"],
        "retrieved_passages": result["retrieved_passages"],
        "temporal_provenance_metadata": result["temporal_provenance_metadata"],
    }


class SynthesizeRequest(BaseModel):
    question: str = Field(
        ...,
        description="The user question to synthesize a grounded answer for",
    )
    top_k: Optional[int] = Field(
        default=5,
        description="Maximum number of passages to retrieve (default: 5)",
    )
    files: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific filenames to restrict retrieval to",
    )


@app.post("/synthesize")
def synthesize_answer(payload: SynthesizeRequest = Body(...)):
    """
    Executes the LangGraph Synthesizer Agent: retrieves relevant passages via the
    Retriever & Chrono-Annotator Agent, then drafts a grounded answer with citations.
    If evidence is insufficient, returns a clear message indicating so.
    Does not treat newer documents as automatically overriding older ones.
    """
    if not payload or not payload.question or not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    # Lazily populate graph if empty
    if tpcg_graph.node_count == 0 and any(UPLOAD_DIR.glob("*.*")):
        tpcg_graph.build_from_directory(UPLOAD_DIR)

    agent = SynthesizerAgent(tpcg=tpcg_graph, upload_dir=UPLOAD_DIR)
    result = agent.run(
        question=payload.question,
        top_k=payload.top_k or 5,
        filter_files=payload.files,
    )

    return {
        "status": "success",
        "question": result["question"],
        "draft_answer": result["draft_answer"],
        "citations": result["citations"],
        "retrieved_evidence": result["retrieved_evidence"],
        "is_sufficiently_supported": result["is_sufficiently_supported"],
        "temporal_provenance_metadata": result["temporal_provenance_metadata"],
    }


class CriticRequest(BaseModel):
    question: str = Field(
        ...,
        description="The original user question that was answered.",
    )
    draft_answer: str = Field(
        ...,
        description="The synthesizer's draft answer to critique.",
    )
    top_k: Optional[int] = Field(
        default=10,
        description="Number of passages to retrieve for critic evidence (default: 10).",
    )
    files: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific filenames to restrict evidence to.",
    )


@app.post("/critic")
def critic_review(payload: CriticRequest = Body(...)):
    """
    Executes the LangGraph Adversarial Red-Team Critic Agent.
    Independently re-retrieves evidence, then checks the draft answer for:
    unsupported claims, missing citations, outdated policy, conflicting rules,
    scope mismatches, incorrect supersession assumptions, and missing evidence.
    Returns a structured verdict: PASS, FLAG, or ABSTAIN.
    """
    if not payload or not payload.question or not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if payload.draft_answer is None:
        raise HTTPException(status_code=400, detail="draft_answer cannot be null.")

    # Lazily populate graph if empty
    if tpcg_graph.node_count == 0 and any(UPLOAD_DIR.glob("*.*")):
        tpcg_graph.build_from_directory(UPLOAD_DIR)

    agent = CriticAgent(tpcg=tpcg_graph, upload_dir=UPLOAD_DIR)
    result = agent.run(
        question=payload.question,
        draft_answer=payload.draft_answer,
        top_k=payload.top_k or 10,
        filter_files=payload.files,
    )

    return {
        "status": "success",
        "question": result["question"],
        "draft_answer": result["draft_answer"],
        "critic_status": result["critic_status"],
        "issues": result["issues"],
        "recommended_action": result["recommended_action"],
        "evidence_summary": result["evidence_summary"],
        "temporal_provenance_metadata": result["temporal_provenance_metadata"],
    }


class ArbitrateRequest(BaseModel):
    question: str = Field(..., description="The user question to arbitrate.")
    top_k: Optional[int] = Field(default=5, description="Passages to retrieve per agent (default: 5).")
    files: Optional[List[str]] = Field(default=None, description="Restrict evidence to these filenames.")


@app.post("/arbitrate")
def arbitrate_answer(payload: ArbitrateRequest = Body(...)):
    """
    Executes the full Retriever → Synthesizer → Critic → Arbitration pipeline.
    Returns outcome: RESOLVED, CONFLICT, or ABSTAIN.
    Never silently resolves conflicts by assuming newest document takes precedence.
    """
    if not payload or not payload.question or not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if tpcg_graph.node_count == 0 and any(UPLOAD_DIR.glob("*.*")):
        tpcg_graph.build_from_directory(UPLOAD_DIR)

    agent = ArbitrationAgent(tpcg=tpcg_graph, upload_dir=UPLOAD_DIR)
    result = agent.run(
        question=payload.question,
        top_k=payload.top_k or 5,
        filter_files=payload.files,
    )

    return {
        "status": "success",
        "question": result["question"],
        "outcome": result["outcome"],
        "final_answer": result["final_answer"],
        "explanation": result["explanation"],
        "citations": result["citations"],
        "conflicting_evidence": result["conflicting_evidence"],
        "abstention_reason": result["abstention_reason"],
        "resolution_basis": result["resolution_basis"],
        "draft_answer": result["draft_answer"],
        "critic_status": result["critic_status"],
        "critic_issues": result["critic_issues"],
        "temporal_provenance_metadata": result["temporal_provenance_metadata"],
    }


class AskRequest(BaseModel):
    question: str = Field(..., description="The user question to answer end-to-end.")
    top_k: Optional[int] = Field(default=5, description="Passages to retrieve per agent stage (default: 5).")
    files: Optional[List[str]] = Field(default=None, description="Restrict evidence to these filenames.")


@app.post("/ask")
def ask_question_endpoint(payload: AskRequest = Body(...)):
    """
    End-to-end TruthGuard-Chronos workflow:
    Retriever & Chrono-Annotator → Synthesizer → Red-Team Critic → Resolution & Arbitration.
    Returns the final outcome (RESOLVED / CONFLICT / ABSTAIN) with the answer, citations,
    and full audit trail.
    """
    if not payload or not payload.question or not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if tpcg_graph.node_count == 0 and any(UPLOAD_DIR.glob("*.*")):
        tpcg_graph.build_from_directory(UPLOAD_DIR)

    workflow = OrchestratorWorkflow(tpcg=tpcg_graph, upload_dir=UPLOAD_DIR)
    result = workflow.run(
        question=payload.question,
        top_k=payload.top_k or 5,
        filter_files=payload.files,
    )

    return {
        "status": "success",
        "question": result["question"],
        "outcome": result["outcome"],
        "final_answer": result["final_answer"],
        "explanation": result["explanation"],
        "citations": result["citations"],
        "conflicting_evidence": result["conflicting_evidence"],
        "abstention_reason": result["abstention_reason"],
        "resolution_basis": result["resolution_basis"],
        "critic_status": result["critic_status"],
        "critic_issues_count": len(result.get("critic_issues", [])),
        "temporal_provenance_metadata": result["temporal_provenance_metadata"],
    }


@app.post("/compare")
def compare_documents_endpoint(payload: CompareRequest = Body(...)):
    """
    Compares two uploaded documents side-by-side using:
    - Document metadata (title, version, issue date, effective date, scope, identifier)
    - TPCG graph relationships (SUPERSEDES, AMENDS, SAME_POLICY, RELATED_TO)
    - Conflict detection and classification (supersession, scope_conflict, temporal_conflict, insufficient_evidence)
    - Extracted text passages and rule differences
    - Returns structured JSON with deterministic outcome (RESOLVED, CONFLICT, ABSTAIN) and citations.
    """
    if not payload:
        raise HTTPException(status_code=400, detail="Missing request body.")

    file_a = (
        payload.file_a
        or payload.doc1
        or payload.doc_a
        or payload.filename_a
        or payload.document1
    )
    file_b = (
        payload.file_b
        or payload.doc2
        or payload.doc_b
        or payload.filename_b
        or payload.document2
    )

    if not file_a or not file_a.strip():
        raise HTTPException(status_code=400, detail="Please provide 'file_a' or 'doc1'.")
    if not file_b or not file_b.strip():
        raise HTTPException(status_code=400, detail="Please provide 'file_b' or 'doc2'.")

    # Lazily populate TPCG graph if empty
    if tpcg_graph.node_count == 0 and any(UPLOAD_DIR.glob("*.*")):
        tpcg_graph.build_from_directory(UPLOAD_DIR)

    try:
        result = compare_two_documents(
            file_a=file_a,
            file_b=file_b,
            tpcg=tpcg_graph,
            upload_dir=UPLOAD_DIR,
        )
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparison failed: {str(e)}")


# ── Compatibility Router for /api/v1 prefix ──
api_v1 = APIRouter(prefix="/api/v1")
api_v1.add_api_route("/health", health_check, methods=["GET"])
api_v1.add_api_route("/upload", upload_file, methods=["POST"])
api_v1.add_api_route("/extract", extract_text, methods=["POST"])
api_v1.add_api_route("/metadata", extract_metadata, methods=["POST"])
api_v1.add_api_route("/graph/rebuild", rebuild_graph, methods=["POST"])
api_v1.add_api_route("/graph", get_graph, methods=["GET"])
api_v1.add_api_route("/conflicts/detect", detect_conflicts, methods=["POST"])
api_v1.add_api_route("/retrieve", retrieve_passages, methods=["POST"])
api_v1.add_api_route("/synthesize", synthesize_answer, methods=["POST"])
api_v1.add_api_route("/critic", critic_review, methods=["POST"])
api_v1.add_api_route("/arbitrate", arbitrate_answer, methods=["POST"])
api_v1.add_api_route("/ask", ask_question_endpoint, methods=["POST"])
api_v1.add_api_route("/compare", compare_documents_endpoint, methods=["POST"])
app.include_router(api_v1)




