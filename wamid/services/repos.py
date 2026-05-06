from __future__ import annotations

import time
from pathlib import Path

from pydantic import BaseModel

from .projects import ProjectNotFound, ProjectService
from .session import Session


class Repo(BaseModel):
    id: int
    path: str
    name: str
    git_author: str | None = None
    project_id: int | None = None
    project_slug: str | None = None
    journal_id: int | None = None
    journal_slug: str | None = None
    created_at: int


class RepoNotFound(Exception):
    def __init__(self, ref: str | int):
        super().__init__(f"repo not found: {ref}")
        self.ref = ref


class RepoConflict(Exception):
    pass


_COLS = (
    "r.id, r.path, r.name, r.git_author, "
    "r.project_id, p.slug, r.journal_id, j.slug, r.created_at"
)
_FROM = (
    "FROM repos r "
    "LEFT JOIN projects p ON p.id = r.project_id "
    "LEFT JOIN journals j ON j.id = r.journal_id"
)


def _row(r) -> Repo:
    return Repo(
        id=r[0], path=r[1], name=r[2], git_author=r[3],
        project_id=r[4], project_slug=r[5],
        journal_id=r[6], journal_slug=r[7],
        created_at=r[8],
    )


def _normalize_path(raw: str) -> str:
    return str(Path(raw).expanduser().resolve())


class RepoService:
    def __init__(self, s: Session):
        self.s = s
        self.c = s.client

    # --- read ----------------------------------------------------------------

    def get(self, ref: str | int) -> Repo:
        """`ref` is an int id or a path string (relative ok, expanded internally)."""
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            rs = self.c.execute(
                f"SELECT {_COLS} {_FROM} WHERE r.id = ?", [int(ref)]
            )
        else:
            rs = self.c.execute(
                f"SELECT {_COLS} {_FROM} WHERE r.path = ?", [_normalize_path(ref)]
            )
        if not rs.rows:
            raise RepoNotFound(ref)
        return _row(rs.rows[0])

    def list(
        self,
        project: str | None = None,
        orphans_only: bool = False,
    ) -> list[Repo]:
        if orphans_only:
            sql = f"SELECT {_COLS} {_FROM} WHERE r.project_id IS NULL ORDER BY r.created_at DESC"
            args: list = []
        elif project is not None:
            pid = self._resolve_project(project)
            sql = f"SELECT {_COLS} {_FROM} WHERE r.project_id = ? ORDER BY r.created_at DESC"
            args = [pid]
        else:
            sql = f"SELECT {_COLS} {_FROM} ORDER BY r.created_at DESC"
            args = []
        return [_row(r) for r in self.c.execute(sql, args).rows]

    # --- write ---------------------------------------------------------------

    def add(
        self,
        path: str,
        name: str | None = None,
        project: str | None = None,
        git_author: str | None = None,
        journal: str | None = None,
    ) -> Repo:
        norm = _normalize_path(path)
        existing = self.c.execute(
            "SELECT id FROM repos WHERE path = ?", [norm]
        )
        if existing.rows:
            raise RepoConflict(f"repo already tracked: {norm}")

        project_id = self._resolve_project(project) if project else None
        journal_id = self._resolve_journal(journal) if journal else None
        repo_name = name or Path(norm).name
        now = int(time.time())
        self.c.execute(
            "INSERT INTO repos (path, name, git_author, project_id, journal_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [norm, repo_name, git_author, project_id, journal_id, now],
        )
        return self.get(norm)

    def update(
        self,
        ref: str | int,
        name: str | None = None,
        git_author: str | None = None,
        journal: str | None = None,
    ) -> Repo:
        repo = self.get(ref)
        sets, args = [], []
        if name is not None:
            sets.append("name = ?"); args.append(name)
        if git_author is not None:
            sets.append("git_author = ?"); args.append(git_author)
        if journal is not None:
            if journal == "":
                sets.append("journal_id = NULL")
            else:
                sets.append("journal_id = ?")
                args.append(self._resolve_journal(journal))
        if sets:
            args.append(repo.id)
            self.c.execute(f"UPDATE repos SET {', '.join(sets)} WHERE id = ?", args)
        return self.get(repo.id)

    def attach(self, ref: str | int, project: str) -> Repo:
        repo = self.get(ref)
        pid = self._resolve_project(project)
        self.c.execute("UPDATE repos SET project_id = ? WHERE id = ?", [pid, repo.id])
        return self.get(repo.id)

    def detach(self, ref: str | int) -> Repo:
        repo = self.get(ref)
        self.c.execute("UPDATE repos SET project_id = NULL WHERE id = ?", [repo.id])
        return self.get(repo.id)

    def delete(self, ref: str | int) -> bool:
        repo = self.get(ref)
        rs = self.c.execute("DELETE FROM repos WHERE id = ?", [repo.id])
        return rs.rows_affected > 0

    # --- helpers -------------------------------------------------------------

    def _resolve_project(self, slug: str) -> int:
        p = ProjectService(self.s).get(slug)
        if not p:
            raise ProjectNotFound(slug)
        return p.id

    def _resolve_journal(self, slug: str) -> int:
        from .journals import JournalService  # local import: avoid cycle
        return JournalService(self.s).resolve(slug)
