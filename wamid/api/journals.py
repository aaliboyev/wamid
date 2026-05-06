from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services.journals import (
    VALID_VISIBILITY,
    Journal,
    JournalConflict,
    JournalNotFound,
    JournalService,
)
from ..services.session import Session
from .deps import session_dep

router = APIRouter(prefix="/journals", tags=["journals"])


class JournalCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    tagline: str | None = None
    visibility: str = "public"
    slug: str | None = None
    color: str | None = None
    emoji: str | None = None
    featured: bool = False


class JournalUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tagline: str | None = None
    visibility: str | None = None
    color: str | None = None
    emoji: str | None = None
    featured: bool | None = None


def _check_visibility(v: str | None):
    if v is not None and v not in VALID_VISIBILITY:
        raise HTTPException(400, f"visibility must be one of {sorted(VALID_VISIBILITY)}")


@router.get("", response_model=list[Journal])
def list_journals(
    visibility: str | None = None,
    s: Session = Depends(session_dep),
):
    _check_visibility(visibility)
    return JournalService(s).list(visibility=visibility)


@router.get("/{slug}", response_model=Journal)
def get_journal(slug: str, s: Session = Depends(session_dep)):
    try:
        return JournalService(s).get(slug)
    except JournalNotFound as e:
        raise HTTPException(404, str(e))


@router.post("", response_model=Journal, status_code=201)
def create_journal(body: JournalCreate, s: Session = Depends(session_dep)):
    _check_visibility(body.visibility)
    try:
        return JournalService(s).add(**body.model_dump())
    except JournalConflict as e:
        raise HTTPException(409, str(e))


@router.patch("/{slug}", response_model=Journal)
def update_journal(slug: str, body: JournalUpdate, s: Session = Depends(session_dep)):
    _check_visibility(body.visibility)
    try:
        return JournalService(s).update(slug, **body.model_dump(exclude_unset=True))
    except JournalNotFound as e:
        raise HTTPException(404, str(e))


@router.delete("/{slug}", status_code=204)
def delete_journal(slug: str, s: Session = Depends(session_dep)):
    try:
        if not JournalService(s).delete(slug):
            raise HTTPException(404, f"journal not found: {slug}")
    except JournalNotFound as e:
        raise HTTPException(404, str(e))
    except JournalConflict as e:
        raise HTTPException(409, str(e))
