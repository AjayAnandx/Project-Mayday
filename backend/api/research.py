from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.core.research_store import get_research_store, RESEARCH_TYPES
from backend.core.report_generator import generate_report as _gen_report, generate_chart as _gen_chart

router = APIRouter(prefix="/api/research", tags=["research"])


class ResearchCreate(BaseModel):
    topic: str
    type: str
    depth: int = 2
    questions: list[str] = []


class ResearchUpdateStatus(BaseModel):
    topic: str
    status: str


class DataPointAdd(BaseModel):
    topic: str
    label: str
    value: str
    unit: Optional[str] = None
    confidence: Optional[str] = None
    sources: list[str] = []


class EntityAdd(BaseModel):
    topic: str
    name: str
    type: str = "company"
    description: Optional[str] = None
    relevance: Optional[float] = None
    sources: list[str] = []


class FindingAdd(BaseModel):
    topic: str
    content: str
    confidence: Optional[str] = None
    sources: list[str] = []


class ChartGenerate(BaseModel):
    topic: str
    chart_type: str = "bar"
    metric: Optional[str] = None


class ReportGenerate(BaseModel):
    topic: str
    format: str = "md"


class CombinedReportGenerate(BaseModel):
    topics: list[str] | None = None
    title: str = "Combined Research Report"
    format: str = "md"


class ResearchNoteAdd(BaseModel):
    filename: str
    content: str


class ResearchPromote(BaseModel):
    topic: str
    name: Optional[str] = None


class AcademicSearchRequest(BaseModel):
    query: str
    max_sources: int = 20
    difficulty: int = 5


class FanOutRequest(BaseModel):
    topic: str
    parent_task_id: Optional[str] = None
    hypotheses: list[str]


@router.get("")
def list_research(status: str = None, q: str = None):
    store = get_research_store()
    if q and q.strip():
        from backend.core.research_index import get_research_index
        return get_research_index().search(q.strip(), limit=20)
    return store.list_projects(status)


@router.post("/academic-search")
def academic_search(body: AcademicSearchRequest):
    from backend.core.academic_search import academic_search as _academic_search
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="Missing query")
    results = _academic_search(body.query.strip(), max_sources=body.max_sources, difficulty=body.difficulty)
    return {"query": body.query, "count": len(results), "results": results}


@router.post("/fan-out", status_code=201)
def fan_out(body: FanOutRequest):
    store = get_research_store()
    result = store.fan_hypothesis(body.topic, body.parent_task_id, body.hypotheses)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


class TaskStatusUpdate(BaseModel):
    task_id: str
    status: str
    result: Optional[str] = None


@router.get("/{topic}/tasks")
def list_tasks(topic: str, status: str = None):
    store = get_research_store()
    result = store.list_tasks(topic, status)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.put("/{topic}/tasks/{task_id}/status")
def update_task_status(topic: str, task_id: str, body: TaskStatusUpdate):
    # allow body.task_id to override URL if provided differently
    tid = body.task_id or task_id
    store = get_research_store()
    result = store.update_task_status(topic, tid, body.status, body.result or "")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{topic}/tasks/{task_id}/freeze")
def freeze_task(topic: str, task_id: str):
    store = get_research_store()
    result = store.freeze_task(topic, task_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/{topic}/artifacts")
def list_artifacts(topic: str):
    store = get_research_store()
    result = store.list_outputs(topic)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("", status_code=201)
def create_research(body: ResearchCreate):
    store = get_research_store()
    result = store.create_research(body.topic, body.type, body.depth, body.questions or None)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/types")
def list_types():
    return list(RESEARCH_TYPES)


@router.get("/{topic}")
def get_research(topic: str):
    store = get_research_store()
    result = store.resume_research(topic)
    if not result:
        raise HTTPException(status_code=404, detail=f"Research '{topic}' not found")
    return result


@router.put("/status")
def update_status(body: ResearchUpdateStatus):
    store = get_research_store()
    result = store.update_status(body.topic, body.status)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Research '{body.topic}' not found")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/data-points", status_code=201)
def add_data_point(body: DataPointAdd):
    store = get_research_store()
    result = store.add_data_point(body.topic, body.label, body.value, body.unit, body.confidence, body.sources)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/entities", status_code=201)
def add_entity(body: EntityAdd):
    store = get_research_store()
    result = store.add_entity(body.topic, body.name, body.type, body.description, body.relevance, body.sources)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/findings", status_code=201)
def add_finding(body: FindingAdd):
    store = get_research_store()
    result = store.add_finding(body.topic, body.content, body.confidence, body.sources)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/generate-chart")
def generate_chart(body: ChartGenerate):
    result = _gen_chart(body.topic, body.chart_type, body.metric)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/generate-report")
def generate_report(body: ReportGenerate):
    result = _gen_report(body.topic, body.format)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/generate-combined-report")
def generate_combined_report(body: CombinedReportGenerate):
    from backend.core.report_generator import generate_combined_report as _gen_combined
    result = _gen_combined(body.topics, body.title, body.format)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{topic}/notes", status_code=201)
def add_research_note(topic: str, body: ResearchNoteAdd):
    store = get_research_store()
    result = store.add_research_note(topic, body.filename, body.content)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/{topic}/notes")
def list_research_notes(topic: str):
    store = get_research_store()
    result = store.list_research_notes(topic)
    if not result and not store._get_by_topic(topic):
        raise HTTPException(status_code=404, detail=f"Research '{topic}' not found")
    return result


@router.get("/{topic}/outputs")
def list_research_outputs(topic: str):
    store = get_research_store()
    result = store.list_outputs(topic)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/promote")
def promote_research(body: ResearchPromote):
    store = get_research_store()
    result = store.promote_to_project(body.topic, body.name)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
