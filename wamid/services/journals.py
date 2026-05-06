from __future__ import annotations

import re
import time
from typing import Any

from pydantic import BaseModel

from .session import Session

DEFAULT_SLUG = "default"
VALID_VISIBILITY = {"public", "private"}


class Journal(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None = None
    tagline: str | None = None
    visibility: str
    color: str | None = None
    emoji: str | None = None
    featured: bool = False
    created_at: int


class JournalNotFound(Exception):
    def __init__(self, ref: str | int):
        super().__init__(f"journal not found: {ref}")
        self.ref = ref


class JournalConflict(Exception):
    pass


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "journal"


_COLS = "id, slug, name, description, tagline, visibility, color, emoji, featured, created_at"


def _row(r) -> Journal:
    return Journal(
        id=r[0], slug=r[1], name=r[2], description=r[3],
        tagline=r[4], visibility=r[5], color=r[6], emoji=r[7],
        featured=bool(r[8]), created_at=r[9],
    )


class JournalService:
    """CRUD for the journal *group* resource. Records live in RecordService."""

    def __init__(self, s: Session):
        self.s = s
        self.c = s.client

    def get(self, ref: str | int) -> Journal:
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            rs = self.c.execute(f"SELECT {_COLS} FROM journals WHERE id = ?", [int(ref)])
        else:
            rs = self.c.execute(f"SELECT {_COLS} FROM journals WHERE slug = ?", [ref])
        if not rs.rows:
            raise JournalNotFound(ref)
        return _row(rs.rows[0])

    def list(self, visibility: str | None = None) -> list[Journal]:
        wheres, args = [], []
        if visibility is not None:
            wheres.append("visibility = ?")
            args.append(visibility)
        sql = f"SELECT {_COLS} FROM journals"
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        sql += " ORDER BY featured DESC, created_at"
        return [_row(r) for r in self.c.execute(sql, args).rows]

    def add(
        self,
        name: str,
        description: str | None = None,
        visibility: str = "public",
        slug: str | None = None,
        tagline: str | None = None,
        color: str | None = None,
        emoji: str | None = None,
        featured: bool = False,
    ) -> Journal:
        if visibility not in VALID_VISIBILITY:
            raise ValueError(f"visibility must be one of {sorted(VALID_VISIBILITY)}")
        slug = slug or _slugify(name)
        existing = self.c.execute("SELECT 1 FROM journals WHERE slug = ?", [slug])
        if existing.rows:
            raise JournalConflict(f"journal slug already exists: {slug}")
        now = int(time.time())
        self.c.execute(
            "INSERT INTO journals (slug, name, description, tagline, visibility, color, emoji, featured, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [slug, name, description, tagline, visibility, color, emoji,
             1 if featured else 0, now],
        )
        return self.get(slug)

    def update(self, ref: str | int, **fields: Any) -> Journal:
        j = self.get(ref)
        sets, args = [], []
        for col in ("name", "description", "tagline", "color", "emoji"):
            if col in fields and fields[col] is not None:
                sets.append(f"{col} = ?"); args.append(fields[col])
        if "visibility" in fields and fields["visibility"] is not None:
            v = fields["visibility"]
            if v not in VALID_VISIBILITY:
                raise ValueError(f"visibility must be one of {sorted(VALID_VISIBILITY)}")
            sets.append("visibility = ?"); args.append(v)
        if "featured" in fields and fields["featured"] is not None:
            sets.append("featured = ?"); args.append(1 if fields["featured"] else 0)
        if sets:
            args.append(j.id)
            self.c.execute(f"UPDATE journals SET {', '.join(sets)} WHERE id = ?", args)
        return self.get(j.id)

    def delete(self, ref: str | int) -> bool:
        j = self.get(ref)
        if j.slug == DEFAULT_SLUG:
            raise JournalConflict("cannot delete the default journal")
        # App-level cascade: libsql client doesn't persist FK PRAGMA across
        # connections, so we delete dependents explicitly here.
        self.c.execute("DELETE FROM records WHERE journal_id = ?", [j.id])
        self.c.execute("DELETE FROM voice WHERE journal_id = ?", [j.id])
        rs = self.c.execute("DELETE FROM journals WHERE id = ?", [j.id])
        return rs.rows_affected > 0

    def resolve(self, slug: str | None) -> int:
        target = slug or DEFAULT_SLUG
        return self.get(target).id
