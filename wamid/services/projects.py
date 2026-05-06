from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .llm import LlmService, ToolCall
from .session import Session
from .voice import VoiceService

VALID_STATUS = {"planning", "active", "shipped", "paused", "archived"}
VALID_VISIBILITY = {"public", "private"}


class ProjectNotFound(Exception):
    """Single source of truth — used by every service that resolves a project slug."""
    def __init__(self, slug: str):
        super().__init__(f"project not found: {slug}")
        self.slug = slug


class Project(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None = None
    tagline: str | None = None
    homepage_url: str | None = None
    repo_url: str | None = None
    started_at: int | None = None
    ended_at: int | None = None
    tags: list[str] = []
    featured: bool = False
    visibility: str = "public"
    color: str | None = None
    emoji: str | None = None
    status: str
    created_at: int
    primary_journal_id: int | None = None
    primary_journal_slug: str | None = None  # denormalized via JOIN


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "project"


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _serialize_tags(tags: list[str] | None) -> str | None:
    if tags is None:
        return None
    cleaned = [t.strip() for t in tags if t and t.strip()]
    return ",".join(cleaned) if cleaned else None


_COLS = (
    "p.id, p.slug, p.name, p.description, p.tagline, p.homepage_url, p.repo_url, "
    "p.started_at, p.ended_at, p.tags, p.featured, p.visibility, p.color, p.emoji, "
    "p.status, p.created_at, p.primary_journal_id, j.slug"
)
_FROM = "FROM projects p LEFT JOIN journals j ON j.id = p.primary_journal_id"


def _row(r) -> Project:
    return Project(
        id=r[0], slug=r[1], name=r[2], description=r[3],
        tagline=r[4], homepage_url=r[5], repo_url=r[6],
        started_at=r[7], ended_at=r[8],
        tags=_parse_tags(r[9]),
        featured=bool(r[10]), visibility=r[11],
        color=r[12], emoji=r[13],
        status=r[14], created_at=r[15],
        primary_journal_id=r[16], primary_journal_slug=r[17],
    )


ASK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a single clarifying question.",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_project",
            "description": "Create the project. Call when you have name and description.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
        },
    },
]


@dataclass
class AskStep:
    history: list[dict] = field(default_factory=list)
    question: str | None = None
    done: bool = False
    result: "Project | None" = None


class ProjectService:
    def __init__(self, s: Session):
        self.s = s
        self.c = s.client

    def add(
        self,
        name: str,
        description: str | None = None,
        slug: str | None = None,
        tagline: str | None = None,
        homepage_url: str | None = None,
        repo_url: str | None = None,
        started_at: int | None = None,
        ended_at: int | None = None,
        tags: list[str] | None = None,
        featured: bool = False,
        visibility: str = "public",
        color: str | None = None,
        emoji: str | None = None,
        status: str = "active",
        primary_journal: str | None = None,
    ) -> Project:
        if visibility not in VALID_VISIBILITY:
            raise ValueError(f"visibility must be one of {sorted(VALID_VISIBILITY)}")
        if status not in VALID_STATUS:
            raise ValueError(f"status must be one of {sorted(VALID_STATUS)}")
        from .journals import JournalService  # local import: avoid cycle
        journal_id = JournalService(self.s).resolve(primary_journal) if primary_journal else None
        slug = slug or _slugify(name)
        now = int(time.time())
        self.c.execute(
            "INSERT INTO projects (slug, name, description, tagline, homepage_url, repo_url, "
            "started_at, ended_at, tags, featured, visibility, color, emoji, status, "
            "created_at, primary_journal_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                slug, name, description, tagline, homepage_url, repo_url,
                started_at, ended_at, _serialize_tags(tags),
                1 if featured else 0, visibility, color, emoji, status, now,
                journal_id,
            ],
        )
        return self.get(slug)  # type: ignore[return-value]

    def get(self, slug: str) -> Project | None:
        rs = self.c.execute(f"SELECT {_COLS} {_FROM} WHERE p.slug = ?", [slug])
        return _row(rs.rows[0]) if rs.rows else None

    def list(
        self,
        include_archived: bool = False,
        visibility: str | None = None,
    ) -> list[Project]:
        wheres, args = [], []
        if not include_archived:
            wheres.append("p.status != 'archived'")
        if visibility is not None:
            wheres.append("p.visibility = ?")
            args.append(visibility)
        sql = f"SELECT {_COLS} {_FROM}"
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        sql += " ORDER BY p.featured DESC, p.created_at DESC"
        return [_row(r) for r in self.c.execute(sql, args).rows]

    def update(self, slug: str, **fields: Any) -> Project | None:
        from .journals import JournalService  # local import: avoid cycle
        sets, args = [], []
        for col in (
            "name", "description", "tagline", "homepage_url", "repo_url",
            "started_at", "ended_at", "color", "emoji",
        ):
            if col in fields and fields[col] is not None:
                sets.append(f"{col} = ?"); args.append(fields[col])
        if "tags" in fields and fields["tags"] is not None:
            sets.append("tags = ?"); args.append(_serialize_tags(fields["tags"]))
        if "featured" in fields and fields["featured"] is not None:
            sets.append("featured = ?"); args.append(1 if fields["featured"] else 0)
        if "visibility" in fields and fields["visibility"] is not None:
            v = fields["visibility"]
            if v not in VALID_VISIBILITY:
                raise ValueError(f"visibility must be one of {sorted(VALID_VISIBILITY)}")
            sets.append("visibility = ?"); args.append(v)
        if "status" in fields and fields["status"] is not None:
            st = fields["status"]
            if st not in VALID_STATUS:
                raise ValueError(f"status must be one of {sorted(VALID_STATUS)}")
            sets.append("status = ?"); args.append(st)
        if "primary_journal" in fields:
            pj = fields["primary_journal"]
            if pj == "":
                sets.append("primary_journal_id = NULL")
            elif pj is not None:
                sets.append("primary_journal_id = ?")
                args.append(JournalService(self.s).resolve(pj))
        if not sets:
            return self.get(slug)
        args.append(slug)
        rs = self.c.execute(
            f"UPDATE projects SET {', '.join(sets)} WHERE slug = ?", args
        )
        if rs.rows_affected == 0:
            return None
        return self.get(slug)

    def archive(self, slug: str) -> bool:
        rs = self.c.execute(
            "UPDATE projects SET status = 'archived' WHERE slug = ?", [slug]
        )
        return rs.rows_affected > 0

    def delete(self, slug: str) -> bool:
        # App-level "ON DELETE SET NULL": detach records and repos first.
        p = self.get(slug)
        if not p:
            return False
        self.c.execute("UPDATE records SET project_id = NULL WHERE project_id = ?", [p.id])
        self.c.execute("UPDATE repos SET project_id = NULL WHERE project_id = ?", [p.id])
        rs = self.c.execute("DELETE FROM projects WHERE id = ?", [p.id])
        return rs.rows_affected > 0

    # --- ask interview -------------------------------------------------------

    def ask_step(
        self,
        llm: LlmService,
        history: list[dict],
        answer: str | None = None,
    ) -> AskStep:
        h = list(history)
        if not h:
            sys_prompt = VoiceService(self.s).template_for("project.ask")
            h.append({"role": "system", "content": sys_prompt})
            h.append({"role": "user", "content": "Let's register a new project."})
        elif answer is not None:
            last = h[-1] if h else {}
            tool_calls = last.get("tool_calls") or []
            ask_call = next(
                (tc for tc in tool_calls if tc.get("function", {}).get("name") == "ask_user"),
                None,
            )
            if ask_call is None:
                raise RuntimeError("answer provided but no pending ask_user tool call")
            h.append({"role": "tool", "tool_call_id": ask_call["id"], "content": answer})

        for _ in range(10):
            turn = llm.step(h, ASK_TOOLS)
            if turn.assistant_message:
                h.append(turn.assistant_message)

            if not turn.tool_calls:
                h.append({"role": "user", "content": "Use the tools (ask_user or submit_project)."})
                continue

            for call in (
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    args=json.loads(tc["function"].get("arguments") or "{}"),
                )
                for tc in turn.assistant_message.get("tool_calls") or []
            ):
                if call.name == "ask_user":
                    return AskStep(history=h, question=call.args.get("question", ""))
                if call.name == "submit_project":
                    try:
                        raw_desc = call.args.get("description") or ""
                        desc = (
                            llm.chat(
                                VoiceService(self.s).template_for("project.describe"),
                                raw_desc,
                            )
                            if raw_desc.strip()
                            else None
                        )
                        p = self.add(name=call.args["name"], description=desc)
                    except Exception as e:
                        h.append({"role": "tool", "tool_call_id": call.id, "content": f"error: {e}"})
                        break
                    h.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": f"created project {p.slug} (id={p.id})",
                    })
                    return AskStep(history=h, done=True, result=p)
                h.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": f"unknown tool: {call.name}",
                })

        raise RuntimeError("ask flow exceeded max iterations")
