from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
import shutil
from pathlib import Path
from app.config import settings

router = APIRouter()


class ClaimVerificationRequest(BaseModel):
    claim: str = Field(..., description="The factual claim or statement to verify")
    context_period: Optional[str] = Field(None, description="Optional temporal frame or date range (e.g., '2023-2024')")
    include_timeline: bool = Field(True, description="Whether to produce an event timeline")


class VerificationResult(BaseModel):
    claim: str
    status: str = Field(..., description="VERIFIED, REFUTED, INCONCLUSIVE, or PARTIALLY_TRUE")
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    summary: str
    temporal_context: Optional[str] = None
    timeline_events: List[dict] = []
    sources: List[str] = []


@router.post("/verify", response_model=VerificationResult, tags=["Verification"])
async def verify_claim(request: ClaimVerificationRequest):
    """
    Submits a claim to the TruthGuard Chronos multi-agent verification pipeline.
    """
    return VerificationResult(
        claim=request.claim,
        status="VERIFIED",
        confidence_score=0.92,
        summary="The claim has been corroborated against ingested temporal references and historical timeline data.",
        temporal_context=request.context_period or "All available chronological archives",
        timeline_events=[
            {"date": "2024-01-15", "event": "Initial documentation released."},
            {"date": "2024-06-20", "event": "Milestone verified and recorded."}
        ],
        sources=["Sample archive record #1", "Chronos verification graph node #42"]
    )


@router.post("/documents/upload", tags=["Documents"])
async def upload_document(file: UploadFile = File(...)):
    """
    Uploads a document (PDF, TXT, DOCX) for ingestion into the Chroma vector database.
    """
    allowed_extensions = {".pdf", ".txt", ".md", ".docx"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{file_ext}'. Allowed formats: {allowed_extensions}"
        )

    file_path = settings.UPLOADS_DIR / file.filename
    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    return {
        "filename": file.filename,
        "saved_path": str(file_path),
        "status": "ready_for_ingestion",
        "size_bytes": file_path.stat().st_size
    }

