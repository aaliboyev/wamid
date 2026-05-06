from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..git import GitError
from ..services.journals import JournalNotFound
from ..services.llm import LlmError, LlmService
from ..services.records import (
    ProjectNotFound,
    Record,
    RecordService,
)
from ..services.session import Session
from .deps import llm_dep, session_dep

router = APIRouter(prefix="/records", tags=["records"])


class FreeformRecord(BaseModel):
    text: str = Field(min_length=1)
    project: str | None = None
    journal: str | None = None
    raw: bool = False


class ScanRequest(BaseModel):
    since: str = "24 hours ago"
    until: str | None = None
    project: str | None = None
    journal: str | None = None


@router.get("", response_model=list[Record])
def list_records(
    project: str | None = None,
    journal: str | None = None,
    limit: int = 50,
    s: Session = Depends(session_dep),
):
    try:
        return RecordService(s).recent(limit=limit, project=project, journal=journal)
    except ProjectNotFound as e:
        raise HTTPException(404, str(e))
    except JournalNotFound as e:
        raise HTTPException(404, str(e))


@router.get("/{record_id}", response_model=Record)
def get_record(record_id: int, s: Session = Depends(session_dep)):
    e = RecordService(s).get(record_id)
    if not e:
        raise HTTPException(404, f"record not found: {record_id}")
    return e


@router.post("", response_model=Record, status_code=201)
def create_record(
    body: FreeformRecord,
    s: Session = Depends(session_dep),
    llm: LlmService = Depends(llm_dep),
):
    try:
        if body.raw:
            return RecordService(s).add(
                text=body.text, source="manual", project=body.project, journal=body.journal,
            )
        return RecordService(s).log(
            text=body.text, llm=llm, project=body.project, journal=body.journal,
        )
    except ProjectNotFound as e:
        raise HTTPException(404, str(e))
    except JournalNotFound as e:
        raise HTTPException(404, str(e))
    except LlmError as e:
        raise HTTPException(502, str(e))


@router.post("/scan", response_model=list[Record])
def scan(
    body: ScanRequest,
    s: Session = Depends(session_dep),
    llm: LlmService = Depends(llm_dep),
):
    """Auto-log every not-yet-logged commit in the window. Returns the new records."""
    try:
        return RecordService(s).scan_and_log(
            llm=llm, since=body.since, until=body.until,
            project=body.project, journal=body.journal,
        )
    except ProjectNotFound as e:
        raise HTTPException(404, str(e))
    except JournalNotFound as e:
        raise HTTPException(404, str(e))
    except GitError as e:
        raise HTTPException(400, str(e))
    except LlmError as e:
        raise HTTPException(502, str(e))


@router.delete("/{record_id}", status_code=204)
def delete_record(record_id: int, s: Session = Depends(session_dep)):
    if not RecordService(s).delete(record_id):
        raise HTTPException(404, f"record not found: {record_id}")
