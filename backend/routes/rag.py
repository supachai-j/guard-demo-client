"""RAG (retrieval-augmented generation) endpoints — upload / generate /
search / clear documents in ChromaDB plus the polling endpoints the
RAG-scanning indicator in the Admin UI hits."""

import os
import shutil

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import auth as _auth
from .. import rag
from ..database import get_db
from ..models import RagSource
from ..schemas import RagGenerateRequest, RagGenerateResponse, RagSearchResponse

router = APIRouter(prefix="/api/rag", tags=["rag"])


@router.post("/generate", response_model=RagGenerateResponse, dependencies=[Depends(_auth.require_admin)])
async def generate_rag_content(request: RagGenerateRequest, db: Session = Depends(get_db)):
    try:
        # Generate content
        markdown = await rag.generate_seed_pack(
            industry=request.industry,
            seed_prompt=request.seed_prompt,
            options={},  # Will be expanded in guided mode
            mode="quick",
        )

        # If not preview only, ingest the content
        if not request.preview_only:
            source_meta = {
                "name": f"Generated Content - {request.industry}",
                "industry": request.industry,
                "seed_prompt": request.seed_prompt,
                "source_type": "generated",
            }
            await rag.ingest_markdown(markdown, source_meta, db)
            return RagGenerateResponse(markdown=markdown, ingested=True)
        else:
            return RagGenerateResponse(markdown=markdown, ingested=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate content: {str(e)}") from e


@router.get("/search", response_model=RagSearchResponse)
async def search_rag_content(query: str, db: Session = Depends(get_db)):
    try:
        results = await rag.retrieve(query, top_k=5)
        return RagSearchResponse(chunks=results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search: {str(e)}") from e


@router.get("/sources")
async def get_rag_sources(db: Session = Depends(get_db)):
    """Get all RAG sources"""
    try:
        sources = db.query(RagSource).order_by(RagSource.created_at.desc()).all()
        return {
            "sources": [
                {
                    "id": source.id,
                    "name": source.name,
                    "source_type": source.source_type,
                    "chunks_count": source.chunks_count,
                    "created_at": source.created_at.isoformat() if source.created_at else None,
                    "updated_at": source.updated_at.isoformat() if source.updated_at else None,
                }
                for source in sources
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get RAG sources: {str(e)}") from e


@router.delete("/clear", dependencies=[Depends(_auth.require_admin)])
async def clear_rag_content(db: Session = Depends(get_db)):
    """Clear all RAG content"""
    try:
        # Clear ChromaDB collection - get all IDs first, then delete them
        try:
            # Get all documents to get their IDs
            all_docs = rag.collection.get()
            if all_docs and all_docs.get("ids"):
                rag.collection.delete(ids=all_docs["ids"])
        except Exception as chroma_error:
            print(f"ChromaDB clear error: {chroma_error}")
            # If ChromaDB fails, continue with database cleanup

        # Clear database sources
        db.query(RagSource).delete()
        db.commit()

        # Clear uploaded files from uploads directory
        uploads_dir = "uploads"
        if os.path.exists(uploads_dir):
            try:
                for filename in os.listdir(uploads_dir):
                    file_path = os.path.join(uploads_dir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        print(f"Deleted uploaded file: {filename}")
            except Exception as file_error:
                print(f"Error deleting uploaded files: {file_error}")
                # Continue even if file deletion fails

        return {"message": "RAG content and uploaded files cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear RAG content: {str(e)}") from e


@router.post("/upload", dependencies=[Depends(_auth.require_admin)])
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload and ingest a file into the RAG system"""
    try:
        # Validate file type
        allowed_types = {
            "application/pdf": ".pdf",
            "text/markdown": ".md",
            "text/plain": ".txt",
            "text/csv": ".csv",
            "application/octet-stream": ".csv",  # Allow CSV files detected as octet-stream
        }

        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File type {file.content_type} not supported. Allowed: {list(allowed_types.keys())}",
            )

        # Validate file size (10MB limit)
        if file.size > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File size exceeds 10MB limit")

        # Create uploads directory if it doesn't exist
        upload_dir = "uploads"
        os.makedirs(upload_dir, exist_ok=True)

        # Save file
        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Ingest file into RAG
        source_meta = {
            "name": file.filename,
            "source_type": "uploaded",
            "file_path": file_path,
            "mimetype": file.content_type,
        }

        result = await rag.ingest_file(file_path, file.content_type, source_meta, db)

        return {"message": "File uploaded and ingested successfully", "filename": file.filename, "result": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}") from e


@router.post("/test-ingest")
async def test_ingest():
    """Test endpoint to ingest sample content"""
    try:
        with open("test_content.md", "r") as f:
            markdown = f.read()

        source_meta = {
            "name": "Digital Banking Guide",
            "industry": "FinTech",
            "source_type": "uploaded",
            "file_path": "test_content.md",
        }

        result = await rag.ingest_markdown(markdown, source_meta)
        return {"message": "Test content ingested", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to ingest test content: {str(e)}") from e


@router.get("/scanning/last")
async def get_last_rag_scanning_result():
    """Get the last RAG content scanning result"""
    result = rag.get_last_rag_scanning_result()
    if result is None:
        raise HTTPException(status_code=404, detail="No RAG scanning result available")
    return result


@router.get("/scanning/progress")
async def get_rag_scanning_progress():
    """Get the current RAG scanning progress"""
    progress = rag.get_rag_scanning_progress()
    if progress is None:
        raise HTTPException(status_code=404, detail="No RAG scanning in progress")
    return progress
