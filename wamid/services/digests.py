from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel

from .llm import LlmService
from .projects import ProjectService
from .session import Session
from .voice import VoiceService

Period = Literal["day", "week", "month"]


class Digest(BaseModel):
    id: int
    project_id: int | None = None
    project_slug: str | None = None
    period: Period
    start_ts: int
    end_ts: int
    text: str


class NoEntriesToDigest(Exception):
    pass


class DigestExists(Exception):
    def __init__(self, period: Period, start_ts: int):
        super().__init__(f"digest already exists for {period} starting at {start_ts}")
        self.period = period
        self.start_ts = start_ts


class ProjectNotFound(Exception):
    def __init__(self, slug: str):
        super().__init__(f"project not found: {slug}")
        self.slug = slug


_COLS = "d.id, d.project_id, p.slug, d.period, d.start_ts, d.end_ts, d.text"
_FROM = "FROM digests d LEFT JOIN projects p ON p.id = d.project_id"


def _row(r) -> Digest:
    return Digest(
        id=r[0], project_id=r[1], project_slug=r[2],
        period=r[3], start_ts=r[4], end_ts=r[5], text=r[6],
    )


def window_for(period: Period, when_ts: int | None = None) -> tuple[int, int]:
    """[start, end) in unix seconds, UTC-bucketed."""
    base = datetime.fromtimestamp(
        when_ts if when_ts is not None else int(datetime.now(timezone.utc).timestamp()),
        tz=timezone.utc,
    )
    if period == "day":
        start = base.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == "week":
        start = (base - timedelta(days=base.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(days=7)
    elif period == "month":
        start = base.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
    else:
        raise ValueError(f"unknown period: {period}")
    return int(start.timestamp()), int(end.timestamp())


class DigestService:
    def __init__(self, s: Session):
        self.s = s
        self.c = s.client

    # --- read ----------------------------------------------------------------

    def get(self, digest_id: int) -> Digest | None:
        rs = self.c.execute(f"SELECT {_COLS} {_FROM} WHERE d.id = ?", [digest_id])
        return _row(rs.rows[0]) if rs.rows else None

    def list(
        self,
        period: Period | None = None,
        project: str | None = None,
        limit: int = 20,
    ) -> list[Digest]:
        wheres, args = [], []
        if period:
            wheres.append("d.period = ?"); args.append(period)
        if project is not None:
            pid = self._resolve_project(project)
            wheres.append("d.project_id = ?"); args.append(pid)
        sql = f"SELECT {_COLS} {_FROM}"
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        sql += " ORDER BY d.start_ts DESC LIMIT ?"
        args.append(limit)
        return [_row(r) for r in self.c.execute(sql, args).rows]

    def find(
        self,
        period: Period,
        start_ts: int,
        project: str | None = None,
    ) -> Digest | None:
        pid = self._resolve_project(project) if project else None
        rs = self.c.execute(
            f"SELECT {_COLS} {_FROM} WHERE d.period = ? AND d.start_ts = ? "
            "AND ((d.project_id IS NULL AND ? IS NULL) OR d.project_id = ?)",
            [period, start_ts, pid, pid],
        )
        return _row(rs.rows[0]) if rs.rows else None

    # --- write ---------------------------------------------------------------

    def generate(
        self,
        llm: LlmService,
        period: Period,
        when_ts: int | None = None,
        project: str | None = None,
        force: bool = False,
    ) -> Digest:
        start_ts, end_ts = window_for(period, when_ts)
        existing = self.find(period, start_ts, project)
        if existing and not force:
            raise DigestExists(period, start_ts)

        pid = self._resolve_project(project) if project else None
        # Read summaries in the window.
        if pid is None:
            rs = self.c.execute(
                "SELECT summary FROM records WHERE ts >= ? AND ts < ? ORDER BY ts",
                [start_ts, end_ts],
            )
        else:
            rs = self.c.execute(
                "SELECT summary FROM records WHERE ts >= ? AND ts < ? AND project_id = ? ORDER BY ts",
                [start_ts, end_ts, pid],
            )
        if not rs.rows:
            raise NoEntriesToDigest(
                f"no records in {period} window [{start_ts}, {end_ts})"
            )

        body = "\n".join(f"- {row[0]}" for row in rs.rows)
        prompt = VoiceService(self.s).template_for(f"digest.{period}")
        text = llm.chat(prompt, body)

        if existing:
            self.c.execute("UPDATE digests SET text = ? WHERE id = ?", [text, existing.id])
            return self.get(existing.id)  # type: ignore[return-value]

        self.c.execute(
            "INSERT INTO digests (project_id, period, start_ts, end_ts, text) "
            "VALUES (?, ?, ?, ?, ?)",
            [pid, period, start_ts, end_ts, text],
        )
        return self.find(period, start_ts, project)  # type: ignore[return-value]

    def delete(self, digest_id: int) -> bool:
        rs = self.c.execute("DELETE FROM digests WHERE id = ?", [digest_id])
        return rs.rows_affected > 0

    # --- helpers -------------------------------------------------------------

    def _resolve_project(self, slug: str) -> int:
        p = ProjectService(self.s).get(slug)
        if not p:
            raise ProjectNotFound(slug)
        return p.id
