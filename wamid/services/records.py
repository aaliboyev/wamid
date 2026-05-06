from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Iterator, Literal

from pydantic import BaseModel

from .. import git
from .journals import JournalService
from .llm import LlmService
from .projects import ProjectNotFound, ProjectService
from .repos import Repo, RepoService
from .session import Session
from .voice import VoiceService


class DuplicateExternal(Exception):
    def __init__(self, external_id: str):
        super().__init__(f"already logged: {external_id}")
        self.external_id = external_id


Source = Literal["commit", "manual", "ask"]


class Record(BaseModel):
    id: int
    journal_id: int
    project_id: int | None = None
    ts: int
    text: str
    summary: str
    source: Source
    source_meta: dict
    external_id: str | None = None


@dataclass
class CommitCandidate:
    repo: Repo
    commit: git.Commit
    already_logged: bool


@dataclass
class BadRepo:
    """A repo that scan couldn't read (bare, no commits, missing dir, etc).
    Surfaces in the scan generator so the CLI can warn without dying."""
    repo: Repo
    error: str


_COLS = "id, journal_id, project_id, ts, text, summary, source, source_meta, external_id"


def _row(r) -> Record:
    return Record(
        id=r[0], journal_id=r[1], project_id=r[2], ts=r[3], text=r[4], summary=r[5],
        source=r[6], source_meta=json.loads(r[7] or "{}"), external_id=r[8],
    )


class RecordService:
    def __init__(self, s: Session):
        self.s = s
        self.c = s.client

    # --- read ----------------------------------------------------------------

    def get(self, record_id: int) -> Record | None:
        rs = self.c.execute(f"SELECT {_COLS} FROM records WHERE id = ?", [record_id])
        return _row(rs.rows[0]) if rs.rows else None

    def recent(
        self,
        limit: int = 20,
        project: str | None = None,
        journal: str | None = None,
    ) -> list[Record]:
        wheres, args = [], []
        if project:
            wheres.append("project_id = ?")
            args.append(self._resolve_project(project))
        if journal:
            wheres.append("journal_id = ?")
            args.append(JournalService(self.s).resolve(journal))
        sql = f"SELECT {_COLS} FROM records"
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        return [_row(r) for r in self.c.execute(sql, args).rows]

    def has_external(self, external_id: str) -> bool:
        rs = self.c.execute(
            "SELECT 1 FROM records WHERE external_id = ? LIMIT 1", [external_id]
        )
        return bool(rs.rows)

    # --- write ---------------------------------------------------------------

    def add(
        self,
        text: str,
        source: Source = "manual",
        summary: str | None = None,
        project: str | None = None,
        journal: str | None = None,
        source_meta: dict | None = None,
        ts: int | None = None,
        external_id: str | None = None,
    ) -> Record:
        """Raw insert. Caller controls summary (or falls back to text)."""
        if external_id and self.has_external(external_id):
            raise DuplicateExternal(external_id)
        journal_id = JournalService(self.s).resolve(journal)
        project_id = self._resolve_project(project)
        summary = summary if summary is not None else text
        ts = ts or int(time.time())
        meta = json.dumps(source_meta or {})
        rs = self.c.execute(
            "INSERT INTO records (journal_id, project_id, ts, text, summary, source, source_meta, external_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            [journal_id, project_id, ts, text, summary, source, meta, external_id],
        )
        return Record(
            id=int(rs.rows[0][0]),
            journal_id=journal_id, project_id=project_id, ts=ts,
            text=text, summary=summary, source=source,
            source_meta=source_meta or {}, external_id=external_id,
        )

    def log(
        self,
        text: str,
        llm: LlmService,
        source: Source = "manual",
        project: str | None = None,
        journal: str | None = None,
        source_meta: dict | None = None,
    ) -> Record:
        """Summarize a freeform record via LLM, then persist. Resolves journal as:
        explicit `journal` arg → project's primary_journal → default."""
        target = journal
        if target is None and project:
            p = ProjectService(self.s).get(project)
            if p and p.primary_journal_slug:
                target = p.primary_journal_slug
        prompt = VoiceService(self.s).template_for("journal.summarize", journal=target)
        summary = llm.chat(prompt, text)
        return self.add(
            text=text, summary=summary, source=source,
            project=project, journal=target, source_meta=source_meta,
        )

    def log_commit(
        self,
        llm: LlmService,
        commit: git.Commit,
        repo: Repo,
        journal: str | None = None,
    ) -> Record:
        """Summarize a single commit and store it. Resolves the destination journal as:
        explicit `journal` arg → repo.journal → repo.project's primary_journal → default."""
        target = journal or repo.journal_slug
        if target is None and repo.project_slug:
            p = ProjectService(self.s).get(repo.project_slug)
            if p and p.primary_journal_slug:
                target = p.primary_journal_slug
        prompt = VoiceService(self.s).template_for("journal.summarize", journal=target)
        summary = llm.chat(prompt, commit.text)
        return self.add(
            text=commit.text,
            summary=summary,
            source="commit",
            project=repo.project_slug,
            journal=target,
            source_meta={
                "sha": commit.sha,
                "repo": repo.path,
                "repo_name": repo.name,
                "author": commit.author,
            },
            ts=commit.ts,
            external_id=commit.sha,
        )

    def scan_and_log(
        self,
        llm: LlmService,
        since: str | None = None,
        until: str | None = None,
        project: str | None = None,
        journal: str | None = None,
    ) -> list[Record]:
        out: list[Record] = []
        for item in self.scan_commits(since=since, until=until, project=project):
            if isinstance(item, BadRepo) or item.already_logged:
                continue
            try:
                out.append(self.log_commit(llm, item.commit, item.repo, journal=journal))
            except DuplicateExternal:
                continue
        return out

    def delete(self, record_id: int) -> bool:
        rs = self.c.execute("DELETE FROM records WHERE id = ?", [record_id])
        return rs.rows_affected > 0

    # --- commit scan ---------------------------------------------------------

    def scan_commits(
        self,
        since: str | None = None,
        until: str | None = None,
        project: str | None = None,
    ) -> Iterator[CommitCandidate | BadRepo]:
        """Yields a CommitCandidate per commit, or a BadRepo per repo that
        couldn't be read. Caller decides how to surface bad repos — a single
        empty / broken repo shouldn't kill the whole scan."""
        repos = RepoService(self.s).list(project=project)
        for repo in repos:
            try:
                commits = git.read_commits(
                    repo.path, since=since, until=until, author=repo.git_author
                )
            except git.GitError as e:
                yield BadRepo(repo=repo, error=str(e))
                continue
            for c in commits:
                yield CommitCandidate(
                    repo=repo, commit=c, already_logged=self.has_external(c.sha)
                )

    # --- helpers -------------------------------------------------------------

    def _resolve_project(self, slug: str | None) -> int | None:
        if not slug:
            return None
        p = ProjectService(self.s).get(slug)
        if not p:
            raise ProjectNotFound(slug)
        return p.id
