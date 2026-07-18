import os
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from pydantic import BaseModel

from backend.core.pdf_store import get_pdf_store
from backend.core.operation_log import get_operation_log
from backend.memory.knowledge_graph import get_graph

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", status_code=201)
async def upload_document(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    store = get_pdf_store()
    try:
        result = store.upload(file_bytes, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    status = result.get("status", "created")
    get_operation_log().record(status, "document", result["id"], result["filename"],
                                details={"pages": result["pages"], "size": result["size"]})

    if status == "created":
        doc_text = store.get_text(result["id"])
        get_graph().sync_document(result, _text=doc_text)

    return result


@router.get("")
def list_documents():
    return get_pdf_store().list_all()


@router.get("/search")
def search_documents(q: str = Query("", min_length=1), limit: int = 10):
    return get_pdf_store().search(q, limit)


@router.get("/{doc_id}")
def get_document(doc_id: str):
    doc = get_pdf_store().get_meta(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{doc_id}/text")
def get_document_text(doc_id: str, pages: str = Query("", description="Comma-separated page numbers")):
    page_list = None
    if pages:
        try:
            page_list = [int(p.strip()) for p in pages.split(",") if p.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid page numbers, use comma-separated integers")
    text = get_pdf_store().get_text(doc_id, page_list)
    if text is None:
        raise HTTPException(status_code=404, detail="Document or page not found")
    return {"doc_id": doc_id, "text": text}


@router.delete("/{doc_id}")
def delete_document(doc_id: str):
    store = get_pdf_store()
    doc = store.get_meta(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    store.delete(doc_id)
    get_graph().delete_document_node(doc_id)
    get_operation_log().record("delete", "document", doc_id, doc.get("filename", doc_id))
    return {"deleted": True}
