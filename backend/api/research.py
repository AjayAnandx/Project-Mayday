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
    return store.list_projects(status or None)  # "?status=" (empty) means no filter


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


# ── evidence-based research runs (Research page) ────────────────────────────

class RunStart(BaseModel):
    topic: str
    request: str = ""
    type: str = "domain"
    preset: str = "standard"            # quick | standard | deep
    questions: Optional[list[str]] = None
    field: Optional[str] = None         # academic: general | cs_ml | social_science
    hypotheses: Optional[list[str]] = None
    snowball: Optional[bool] = None
    sources: Optional[list[str]] = None  # per-run adapter allow-list


class RunExport(BaseModel):
    format: str = "docx"                # docx | xlsx


def _record_or_404(topic: str) -> dict:
    record = get_research_store()._get_by_topic(topic)
    if not record:
        raise HTTPException(status_code=404, detail=f"Research '{topic}' not found")
    return record


def _run_summary(r: dict) -> dict:
    return {k: r.get(k) for k in ("id", "status", "stage", "usage", "budget", "error", "started_at",
                                  "finished_at", "outputs")} | {
        "questions": (r.get("brief") or {}).get("questions", []),
        "answered": sum(1 for a in r.get("answers") or [] if a.get("answer")),
    }


@router.post("/runs")
def start_run(body: RunStart):
    from backend.core.research_flow import start_research_run
    from backend.functions.research_flow_functions import BUDGET_PRESETS
    if not body.topic.strip():
        raise HTTPException(status_code=400, detail="topic is required")
    rtype = body.type if body.type in RESEARCH_TYPES else "domain"
    res = start_research_run(body.topic.strip(), request=body.request or body.topic,
                             questions=[q for q in (body.questions or []) if q.strip()] or None,
                             research_type=rtype, budget=dict(BUDGET_PRESETS.get(body.preset, {})),
                             options={"field": body.field, "hypotheses": [h for h in (body.hypotheses or []) if h.strip()],
                                      "snowball": body.snowball, "sources": body.sources or []})
    if "error" in res:
        raise HTTPException(status_code=409, detail=res["error"])
    return res


@router.get("/{topic}/runs")
def list_runs(topic: str):
    record = _record_or_404(topic)
    return [_run_summary(r) for r in reversed(record.get("runs", []))]


@router.get("/{topic}/runs/{run_id}")
def get_run(topic: str, run_id: str):
    record = _record_or_404(topic)
    run = next((r for r in record.get("runs", []) if r["id"] == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    from backend.core.research_report import _render_answer, _source_numbering
    claim_refs, sources = _source_numbering(record, run.get("answers") or [])
    answers = [{**a, "rendered": _render_answer(a, claim_refs)} for a in run.get("answers") or []]
    return {**run, "answers": answers,
            "cited_sources": [{"n": n, **{k: s.get(k) for k in ("id", "title", "url", "type", "tier",
                                                                  "published_date", "access", "evidence_status", "is_retracted", "is_oa", "oa_pdf_url", "authors", "venue", "year", "doi", "arxiv_id")}}
                              for n, s in enumerate(sources, 1)],
            "claim_refs": claim_refs}


@router.get("/{topic}/runs/{run_id}/report")
def get_run_report(topic: str, run_id: str):
    from pathlib import Path
    record = _record_or_404(topic)
    path = get_research_store().get_reports_dir(record) / f"run-{run_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not written yet")
    return {"markdown": Path(path).read_text(encoding="utf-8"),
            "url": f"/research/{record['slug']}/artifacts/reports/{path.name}"}


@router.post("/{topic}/runs/{run_id}/export")
def export_run_file(topic: str, run_id: str, body: RunExport):
    from backend.core.research_export import export_run
    res = export_run(topic, run_id, body.format)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@router.get("/{topic}/claims")
def list_claims(topic: str, status: Optional[str] = None, limit: int = 300):
    record = _record_or_404(topic)
    srcs = {s["id"]: s for s in record.get("sources", [])}
    out = []
    for c in sorted(record.get("claims", []), key=lambda c: -c.get("confidence", 0)):
        if status and c["status"] != status:
            continue
        e = next((x for x in c["evidence"] if x.get("verified")), c["evidence"][0] if c["evidence"] else {})
        s = srcs.get(e.get("source_id", ""), {})
        out.append({k: c.get(k) for k in ("id", "statement", "status", "confidence", "confidence_reasons",
                                          "kind", "value", "unit", "as_of", "question", "run_id", "study",
                                          "evidence_level", "hypothesis_id", "hypothesis_stance")}
                   | {"quote": e.get("quote", ""), "verified": e.get("verified"),
                      "source": {"id": s.get("id"), "title": s.get("title"), "url": s.get("url"),
                                 "tier": s.get("tier"), "evidence_status": s.get("evidence_status")}})
        if len(out) >= limit:
            break
    return out


@router.get("/{topic}/sources")
def list_sources(topic: str):
    record = _record_or_404(topic)
    counts: dict[str, int] = {}
    for c in record.get("claims", []):
        if c["status"] in ("supported", "contested"):
            for e in c["evidence"]:
                if e.get("verified"):
                    counts[e["source_id"]] = counts.get(e["source_id"], 0) + 1
    return [{k: s.get(k) for k in ("id", "title", "url", "type", "tier", "publisher", "published_date",
                                    "access", "fetched_at", "content_hash", "evidence_status", "is_retracted", "is_oa", "oa_pdf_url", "authors", "venue", "year", "doi", "arxiv_id")} | {"verified_claims": counts.get(s["id"], 0)}
            for s in record.get("sources", [])]


@router.get("/meta/adapters")
def list_adapters():
    """Source adapters usable right now (for per-run source toggles)."""
    from backend.core.research_sources import available_adapters
    return [{"name": n, "description": a.description} for n, a in available_adapters().items()]


@router.get("/{topic}/cite")
def cite(topic: str, style: str = "bibtex", run_id: str = ""):
    from backend.functions.research_flow_functions import research_cite
    _record_or_404(topic)
    text = research_cite(topic, style, run_id)
    if text.startswith("Style must be"):
        raise HTTPException(status_code=400, detail=text)
    return {"style": style, "text": text}
