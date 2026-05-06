from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Iterator, Literal

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


def _compose_system(template: str, *, project=None, repo: Repo | None = None) -> str:
    """Append a structured Context block to the voice template so the LLM
    knows what 'this' is when summarizing. Project tagline + description and
    repo description give the model the framing it needs to translate
    technical commit messages into plain language for non-technical readers.
    """
    bits: list[str] = []
    if project is not None:
        line = f"- project: {project.name}"
        if project.tagline:
            line += f" — {project.tagline}"
        bits.append(line)
        if project.description:
            bits.append(f"  about: {project.description}")
    if repo is not None:
        line = f"- repo: {repo.name}"
        if repo.description:
            line += f" — {repo.description}"
        bits.append(line)
    if not bits:
        return template
    return f"{template}\n\nContext for this entry:\n" + "\n".join(bits)


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
        project_obj = ProjectService(self.s).get(project) if project else None
        if target is None and project_obj and project_obj.primary_journal_slug:
            target = project_obj.primary_journal_slug
        template = VoiceService(self.s).template_for("journal.summarize", journal=target)
        system = _compose_system(template, project=project_obj)
        summary = llm.chat(system, text)
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
        project_obj = (
            ProjectService(self.s).get(repo.project_slug) if repo.project_slug else None
        )
        if target is None and project_obj and project_obj.primary_journal_slug:
            target = project_obj.primary_journal_slug
        template = VoiceService(self.s).template_for("journal.summarize", journal=target)
        system = _compose_system(template, project=project_obj, repo=repo)
        summary = llm.chat(system, commit.text)
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
        parallel: int = 5,
        on_each: Callable[[CommitCandidate, Record | None, Exception | None], None] | None = None,
    ) -> list[Record]:
        """Auto-mode batch scan: summarize new commits in parallel, write sequentially.

        - LLM calls fan out across `parallel` worker threads (httpx.Client is
          thread-safe; Ollama serves concurrent requests fine).
        - DB inserts run on the main thread (libsql_client is per-call sync,
          and inserts are cheap).
        - `on_each(cand, record, error)` fires as each commit lands, so callers
          can stream feedback without buffering all results.
        """
        candidates: list[CommitCandidate] = []
        for item in self.scan_commits(since=since, until=until, project=project):
            if isinstance(item, BadRepo) or item.already_logged:
                continue
            candidates.append(item)
        if not candidates:
            return []

        # Resolve target journal + build voiced system prompt per commit (sync, cheap).
        prepared: list[tuple[CommitCandidate, str | None, str]] = []
        psvc = ProjectService(self.s)
        vsvc = VoiceService(self.s)
        for cand in candidates:
            target = journal or cand.repo.journal_slug
            project_obj = psvc.get(cand.repo.project_slug) if cand.repo.project_slug else None
            if target is None and project_obj and project_obj.primary_journal_slug:
                target = project_obj.primary_journal_slug
            template = vsvc.template_for("journal.summarize", journal=target)
            system = _compose_system(template, project=project_obj, repo=cand.repo)
            prepared.append((cand, target, system))

        def summarize(item):
            cand, target, system = item
            try:
                return (cand, target, llm.chat(system, cand.commit.text), None)
            except Exception as e:
                return (cand, target, None, e)

        out: list[Record] = []
        # Cap workers at the number of items so we don't spin idle threads.
        workers = max(1, min(parallel, len(prepared)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(summarize, item) for item in prepared]
            for fut in as_completed(futures):
                cand, target, summary, error = fut.result()
                if error is not None:
                    if on_each:
                        on_each(cand, None, error)
                    continue
                try:
                    record = self.add(
                        text=cand.commit.text, summary=summary, source="commit",
                        project=cand.repo.project_slug, journal=target,
                        source_meta={
                            "sha": cand.commit.sha, "repo": cand.repo.path,
                            "repo_name": cand.repo.name, "author": cand.commit.author,
                        },
                        ts=cand.commit.ts, external_id=cand.commit.sha,
                    )
                except DuplicateExternal:
                    continue
                out.append(record)
                if on_each:
                    on_each(cand, record, None)
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
