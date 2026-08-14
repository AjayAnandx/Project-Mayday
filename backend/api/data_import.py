from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse

from backend.functions.data_import import (
    import_data,
    import_data_to_store,
    list_imported_files,
    save_uploaded_file,
)

router = APIRouter(prefix="/api/data", tags=["data-import"])


@router.post("/import")
async def upload_file(file: UploadFile = File(...)):
    """Upload an Excel/CSV file and return file_id."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail="Only .xlsx, .xls, .csv files allowed")
    
    content = await file.read()
    file_id = save_uploaded_file(content, file.filename)
    
    return {"file_id": file_id, "filename": file.filename, "size": len(content)}


@router.post("/parse")
async def parse_file(
    file_id: str = Form(...),
    sheet_name: str = Form(default=None),
    header_row: int = Form(default=0),
):
    """Parse an uploaded file and return structured data preview."""
    result = import_data(file_id, sheet_name, header_row)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/import-to-store")
async def import_to_store(
    file_id: str = Form(...),
    sheet_name: str = Form(default=None),
    header_row: int = Form(default=0),
    store_type: str = Form(...),
    topic: str = Form(default=None),
    project_name: str = Form(default=None),
):
    """Import parsed data into research or project as data_points."""
    result = import_data_to_store(file_id, sheet_name, header_row, store_type, topic, project_name)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/files")
async def list_files():
    """List all uploaded files."""
    return {"files": list_imported_files()}