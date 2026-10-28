import shutil
import uuid
import re
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TruthGuard-Chronos API")

# Configure CORS to allow local Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure upload directory exists inside backend/uploads/
UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".txt"}


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
