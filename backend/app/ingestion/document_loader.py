from pathlib import Path
from typing import List, Dict, Any


class DocumentIngestionPipeline:
    """
    Handles file ingestion, chunking, and temporal metadata extraction.
    """

    def __init__(self, upload_dir: Path):
        self.upload_dir = upload_dir

    def process_document(self, file_path: Path) -> List[Dict[str, Any]]:
        """
        Loads and splits a document into chunks ready for vector indexing.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Stub ingestion logic
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        return [
            {
                "chunk_id": f"{file_path.stem}_chunk_0",
                "text": content[:1000],
                "metadata": {
                    "source": file_path.name,
                    "timestamp": None,
                }
            }
        ]

