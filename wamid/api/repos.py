from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services.repos import (
    ProjectNotFound,
    Repo,
    RepoConflict,
    RepoNotFound,
    RepoService,
)
from ..services.session import Session
from .deps import session_dep

router = APIRouter(prefix="/repos", tags=["repos"])


class RepoCreate(BaseModel):
    path: str = Field(min_length=1)
    name: str | None = None
    description: str | None = None
    project: str | None = None
    journal: str | None = None
    git_author: str | None = None


class RepoUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    git_author: str | None = None
    journal: str | None = None  # empty string clears


class AttachBody(BaseModel):
    project: str


@router.get("", response_model=list[Repo])
def list_repos(
    project: str | None = None,
    orphans: bool = False,
    s: Session = Depends(session_dep),
):
    try:
        return RepoService(s).list(project=project, orphans_only=orphans)
    except ProjectNotFound as e:
        raise HTTPException(404, str(e))


@router.get("/{repo_id}", response_model=Repo)
def get_repo(repo_id: int, s: Session = Depends(session_dep)):
    try:
        return RepoService(s).get(repo_id)
    except RepoNotFound as e:
        raise HTTPException(404, str(e))


@router.post("", response_model=Repo, status_code=201)
def create_repo(body: RepoCreate, s: Session = Depends(session_dep)):
    try:
        return RepoService(s).add(
            path=body.path, name=body.name, description=body.description,
            project=body.project, git_author=body.git_author,
            journal=body.journal,
        )
    except RepoConflict as e:
        raise HTTPException(409, str(e))
    except ProjectNotFound as e:
        raise HTTPException(404, str(e))


@router.patch("/{repo_id}", response_model=Repo)
def update_repo(repo_id: int, body: RepoUpdate, s: Session = Depends(session_dep)):
    try:
        return RepoService(s).update(
            repo_id, name=body.name, description=body.description,
            git_author=body.git_author, journal=body.journal,
        )
    except RepoNotFound as e:
        raise HTTPException(404, str(e))


@router.post("/{repo_id}/attach", response_model=Repo)
def attach_repo(repo_id: int, body: AttachBody, s: Session = Depends(session_dep)):
    try:
        return RepoService(s).attach(repo_id, body.project)
    except (RepoNotFound, ProjectNotFound) as e:
        raise HTTPException(404, str(e))


@router.post("/{repo_id}/detach", response_model=Repo)
def detach_repo(repo_id: int, s: Session = Depends(session_dep)):
    try:
        return RepoService(s).detach(repo_id)
    except RepoNotFound as e:
        raise HTTPException(404, str(e))


@router.delete("/{repo_id}", status_code=204)
def delete_repo(repo_id: int, s: Session = Depends(session_dep)):
    try:
        if not RepoService(s).delete(repo_id):
            raise HTTPException(404, f"repo not found: {repo_id}")
    except RepoNotFound as e:
        raise HTTPException(404, str(e))
