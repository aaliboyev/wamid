from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services.projects import (
    VALID_STATUS,
    VALID_VISIBILITY,
    Project,
    ProjectService,
)
from ..services.session import Session
from .deps import session_dep

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    slug: str | None = None
    tagline: str | None = None
    homepage_url: str | None = None
    repo_url: str | None = None
    started_at: int | None = None
    ended_at: int | None = None
    tags: list[str] | None = None
    featured: bool = False
    visibility: str = "public"
    status: str = "active"
    color: str | None = None
    emoji: str | None = None
    primary_journal: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tagline: str | None = None
    homepage_url: str | None = None
    repo_url: str | None = None
    started_at: int | None = None
    ended_at: int | None = None
    tags: list[str] | None = None
    featured: bool | None = None
    visibility: str | None = None
    status: str | None = None
    color: str | None = None
    emoji: str | None = None
    primary_journal: str | None = None  # empty string clears


def _check_enums(visibility: str | None, status: str | None):
    if visibility is not None and visibility not in VALID_VISIBILITY:
        raise HTTPException(400, f"visibility must be one of {sorted(VALID_VISIBILITY)}")
    if status is not None and status not in VALID_STATUS:
        raise HTTPException(400, f"status must be one of {sorted(VALID_STATUS)}")


@router.get("", response_model=list[Project])
def list_projects(
    include_archived: bool = False,
    visibility: str | None = None,
    s: Session = Depends(session_dep),
):
    return ProjectService(s).list(include_archived=include_archived, visibility=visibility)


@router.get("/{slug}", response_model=Project)
def get_project(slug: str, s: Session = Depends(session_dep)):
    p = ProjectService(s).get(slug)
    if not p:
        raise HTTPException(404, f"project not found: {slug}")
    return p


@router.post("", response_model=Project, status_code=201)
def create_project(body: ProjectCreate, s: Session = Depends(session_dep)):
    _check_enums(body.visibility, body.status)
    return ProjectService(s).add(**body.model_dump())


@router.patch("/{slug}", response_model=Project)
def update_project(slug: str, body: ProjectUpdate, s: Session = Depends(session_dep)):
    _check_enums(body.visibility, body.status)
    p = ProjectService(s).update(slug, **body.model_dump(exclude_unset=True))
    if not p:
        raise HTTPException(404, f"project not found: {slug}")
    return p


@router.delete("/{slug}", status_code=204)
def delete_project(slug: str, s: Session = Depends(session_dep)):
    if not ProjectService(s).delete(slug):
        raise HTTPException(404, f"project not found: {slug}")
