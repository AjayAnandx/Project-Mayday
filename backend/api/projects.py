from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.core.project_store import get_project_store

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None


class DataPointAdd(BaseModel):
    label: str
    value: str
    unit: Optional[str] = None
    confidence: Optional[str] = None
    sources: list[str] = []


class ChartGenerate(BaseModel):
    chart_type: str = "auto"
    metric: Optional[str] = None


@router.get("")
def list_projects(status: str = ""):
    store = get_project_store()
    return store.list_projects(status=status or None)


@router.get("/{project_id}")
def get_project(project_id: str):
    store = get_project_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("", status_code=201)
def create_project(body: ProjectCreate):
    store = get_project_store()
    result = store.create_project(body.name)
    if "error" in result:
        raise HTTPException(status_code=409, detail=result["error"])
    return result


@router.put("/{project_id}")
def update_project(project_id: str, body: ProjectUpdate):
    store = get_project_store()
    if body.status is not None:
        valid = ("active", "paused", "scrapped")
        if body.status not in valid:
            raise HTTPException(status_code=400, detail=f"Status must be one of {valid}")
        project = store.update_project_status(project_id, body.status)
    elif body.name is not None:
        project = store.update_project_name(project_id, body.name)
    else:
        project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}")
def delete_project(project_id: str):
    store = get_project_store()
    project = store.soft_delete(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": True, "project": project}


@router.post("/{project_id}/data-points", status_code=201)
def add_data_point(project_id: str, body: DataPointAdd):
    store = get_project_store()
    result = store.add_data_point(project_id, body.label, body.value, body.unit, body.confidence, body.sources)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/{project_id}/data-points")
def list_data_points(project_id: str):
    store = get_project_store()
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return store.list_data_points(project_id)


@router.get("/{project_id}/outputs")
def list_project_outputs(project_id: str):
    store = get_project_store()
    result = store.list_outputs(project_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{project_id}/generate-chart")
def generate_chart(project_id: str, body: ChartGenerate):
    from backend.core.report_generator import generate_project_chart as _gen
    result = _gen(project_id, body.chart_type, body.metric)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
