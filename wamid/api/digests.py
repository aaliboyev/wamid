from fastapi import APIRouter, Depends, HTTPException

from ..services.digests import Digest, DigestService, ProjectNotFound
from ..services.session import Session
from .deps import session_dep

router = APIRouter(prefix="/digests", tags=["digests"])


@router.get("", response_model=list[Digest])
def list_digests(
    period: str | None = None,
    project: str | None = None,
    limit: int = 20,
    s: Session = Depends(session_dep),
):
    if period and period not in ("day", "week", "month"):
        raise HTTPException(400, "period must be day, week, or month")
    try:
        return DigestService(s).list(period=period, project=project, limit=limit)  # type: ignore[arg-type]
    except ProjectNotFound as e:
        raise HTTPException(404, str(e))


@router.get("/{digest_id}", response_model=Digest)
def get_digest(digest_id: int, s: Session = Depends(session_dep)):
    d = DigestService(s).get(digest_id)
    if not d:
        raise HTTPException(404, f"digest not found: {digest_id}")
    return d
