from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import BaseModel

from .journals import JournalNotFound, JournalService
from .llm import LlmService
from .session import Session

# Built-in defaults. Each key is a feature the app supports a voice for.
# Adding a new LLM-driven feature means adding an entry here AND wiring a
# service to call VoiceService.template_for(<purpose>, journal=...).
PURPOSES: dict[str, str] = {
    "journal.summarize": """\
You rewrite engineering work notes into one or two short, plain-language sentences \
that a non-technical reader can follow. No jargon, no hype, no emojis. \
First person, present-or-past tense matching the input. \
Do not invent details. Output only the rewritten sentence(s), nothing else.""",
    "digest.day": """\
You write a daily digest of someone's work. You receive a list of one-line summaries from \
today's records. Produce one short paragraph (3–5 sentences) that reads like a human telling \
a friend what they got done today. Group related items naturally; don't repeat. \
No bullet lists, no headers, no emojis. First person, past tense. Output only the paragraph.""",
    "digest.week": """\
You write a weekly digest from this week's daily summaries. Produce 1–2 short paragraphs that \
surface the themes and arcs of the week — what shipped, what's brewing, what shifted. Don't list. \
First person, past tense, plain language. Output only the paragraphs.""",
    "digest.month": """\
You write a monthly digest from this month's weekly summaries. Produce 2–3 short paragraphs \
that capture the month's arc: what got built, what learned, what changed. Surface patterns. \
First person, past tense, plain language. Output only the paragraphs.""",
    "project.describe": """\
You rewrite a raw project description into one short paragraph (2–4 sentences) that a \
non-technical reader can follow. Keep what makes the project distinctive. No jargon, no hype, \
no emojis. Plain present tense. Do not invent details. Output only the rewritten paragraph, \
nothing else.""",
    "project.ask": """\
You are interviewing the user to register a new project in their personal-narrative tool.

Goal: collect a name, a one-paragraph description in plain language (what it is and why \
it exists). Slug is auto-generated from the name; don't ask for it.

Rules:
- Use the `ask_user` tool to ask ONE focused question at a time. Keep questions short.
- Don't repeat what the user just told you. Don't say "got it" or "great." Just ask the next thing.
- When you have name + description, call `submit_project`. Don't ask for confirmation.
- If `submit_project` returns an error, fix it and try again — don't bother the user unless the user must decide.""",
}

DEFAULT_NAME = "default"  # reserved name representing the built-in template


CRAFT_VOICE_PROMPT = """\
You are helping the user craft a system prompt (a "voice") used by their tool for a specific purpose.

Purpose: {purpose}
Scope: {scope}
Currently active template:
---
{current}
---

Ask the user about tone (casual/formal/dry), length, first vs third person, what to avoid \
(jargon, hype, emojis), and any signature phrases or hard constraints. Use the `ask_user` tool. \
One short question at a time. Don't repeat what the user just told you.

Also ask the user for a short name for this voice variant (e.g. "dry", "casual", "formal").

When you have enough, draft a complete standalone system prompt that fits this purpose and call \
`submit_voice` with the name and the prompt. Write the prompt as imperative instructions in plain \
English — not as a list of preferences. The prompt must be self-contained: the LLM that uses it \
won't see this conversation."""


CRAFT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user one focused clarifying question.",
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
            "name": "submit_voice",
            "description": "Save the crafted system prompt as a new voice variant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short name for this voice (e.g. 'dry', 'casual').",
                    },
                    "template": {
                        "type": "string",
                        "description": "Complete standalone system prompt.",
                    },
                },
                "required": ["name", "template"],
            },
        },
    },
]


class Voice(BaseModel):
    id: int | None = None  # None for the built-in default
    purpose: str
    name: str
    template: str
    active: bool
    is_default: bool
    journal_id: int | None = None
    journal_slug: str | None = None  # None means global scope


class UnknownPurpose(Exception):
    def __init__(self, name: str):
        super().__init__(f"unknown voice purpose: {name}")
        self.name = name


class VoiceNotFound(Exception):
    def __init__(self, purpose: str, name: str, journal: str | None = None):
        scope = f" (journal={journal})" if journal else " (global)"
        super().__init__(f"voice not found: {purpose}/{name}{scope}")
        self.purpose = purpose
        self.name = name
        self.journal = journal


class VoiceConflict(Exception):
    pass


@dataclass
class CraftStep:
    history: list[dict] = field(default_factory=list)
    question: str | None = None
    done: bool = False
    result: Voice | None = None


def _ensure_purpose(purpose: str) -> None:
    if purpose not in PURPOSES:
        raise UnknownPurpose(purpose)


def _row(r) -> Voice:
    return Voice(
        id=r[0], purpose=r[1], name=r[2], template=r[3],
        active=bool(r[4]), is_default=False,
        journal_id=r[5], journal_slug=r[6],
    )


def _default_voice(purpose: str, journal_slug: str | None = None) -> Voice:
    return Voice(
        id=None, purpose=purpose, name=DEFAULT_NAME,
        template=PURPOSES[purpose], active=False, is_default=True,
        journal_id=None, journal_slug=journal_slug,
    )


_COLS = "v.id, v.purpose, v.name, v.template, v.active, v.journal_id, j.slug"
_FROM = "FROM voice v LEFT JOIN journals j ON j.id = v.journal_id"


class VoiceService:
    def __init__(self, s: Session):
        self.s = s
        self.c = s.client

    @staticmethod
    def purposes() -> list[str]:
        return list(PURPOSES.keys())

    # --- read ----------------------------------------------------------------

    def template_for(self, purpose: str, journal: str | None = None) -> str:
        """Pick the active template for (purpose, journal). Priority:
        1. journal-scoped active voice for that journal
        2. global active voice for purpose
        3. built-in default
        """
        _ensure_purpose(purpose)
        if journal:
            jid = JournalService(self.s).resolve(journal)
            rs = self.c.execute(
                "SELECT template FROM voice WHERE purpose = ? AND journal_id = ? AND active = 1",
                [purpose, jid],
            )
            if rs.rows:
                return str(rs.rows[0][0])
        rs = self.c.execute(
            "SELECT template FROM voice WHERE purpose = ? AND journal_id IS NULL AND active = 1",
            [purpose],
        )
        if rs.rows:
            return str(rs.rows[0][0])
        return PURPOSES[purpose]

    def list(
        self,
        purpose: str | None = None,
        journal: str | None = None,
    ) -> list[Voice]:
        """Synthetic 'default' rows are included so the consumer always sees the
        full set of purposes and which is active in scope."""
        if purpose is not None:
            _ensure_purpose(purpose)
            purposes = [purpose]
        else:
            purposes = list(PURPOSES.keys())

        # Build SQL filter
        wheres, args = ["v.purpose IN ({})".format(",".join(["?"] * len(purposes)))], list(purposes)
        if journal is not None:
            jid = JournalService(self.s).resolve(journal)
            wheres.append("v.journal_id = ?")
            args.append(jid)
        sql = f"SELECT {_COLS} {_FROM} WHERE " + " AND ".join(wheres) + " ORDER BY v.purpose, v.journal_id, v.name"
        rows = [_row(r) for r in self.c.execute(sql, args).rows]

        out: list[Voice] = []
        for p in purposes:
            customs = [v for v in rows if v.purpose == p]
            # Within this purpose, mark default active when no custom in this scope is active.
            if journal is not None:
                has_active = any(v.active and v.journal_slug == journal for v in customs)
                default = _default_voice(p, journal_slug=journal)
            else:
                has_active = any(v.active and v.journal_id is None for v in customs)
                default = _default_voice(p)
            default.active = not has_active
            out.append(default)
            out.extend(customs)
        return out

    def get(
        self,
        purpose: str,
        name: str | None = None,
        journal: str | None = None,
    ) -> Voice:
        """Without `name`: returns the active voice in the given scope (custom or default).
        With `name`: returns that specific voice. `journal` selects scope (None = global)."""
        _ensure_purpose(purpose)
        jid = JournalService(self.s).resolve(journal) if journal else None

        if name is None:
            if jid is not None:
                rs = self.c.execute(
                    f"SELECT {_COLS} {_FROM} WHERE v.purpose = ? AND v.journal_id = ? AND v.active = 1",
                    [purpose, jid],
                )
                if rs.rows:
                    return _row(rs.rows[0])
            rs = self.c.execute(
                f"SELECT {_COLS} {_FROM} WHERE v.purpose = ? AND v.journal_id IS NULL AND v.active = 1",
                [purpose],
            )
            if rs.rows:
                return _row(rs.rows[0])
            return _default_voice(purpose, journal_slug=journal)

        if name == DEFAULT_NAME:
            return _default_voice(purpose, journal_slug=journal)

        if jid is None:
            rs = self.c.execute(
                f"SELECT {_COLS} {_FROM} WHERE v.purpose = ? AND v.name = ? AND v.journal_id IS NULL",
                [purpose, name],
            )
        else:
            rs = self.c.execute(
                f"SELECT {_COLS} {_FROM} WHERE v.purpose = ? AND v.name = ? AND v.journal_id = ?",
                [purpose, name, jid],
            )
        if not rs.rows:
            raise VoiceNotFound(purpose, name, journal)
        return _row(rs.rows[0])

    # --- write ---------------------------------------------------------------

    def add(
        self,
        purpose: str,
        name: str,
        template: str,
        journal: str | None = None,
    ) -> Voice:
        _ensure_purpose(purpose)
        if name == DEFAULT_NAME:
            raise VoiceConflict(f"name '{DEFAULT_NAME}' is reserved for the built-in")

        jid = JournalService(self.s).resolve(journal) if journal else None

        # First voice for this (purpose, scope) auto-activates.
        if jid is None:
            existing = self.c.execute(
                "SELECT COUNT(*) FROM voice WHERE purpose = ? AND journal_id IS NULL",
                [purpose],
            )
        else:
            existing = self.c.execute(
                "SELECT COUNT(*) FROM voice WHERE purpose = ? AND journal_id = ?",
                [purpose, jid],
            )
        active = 1 if int(existing.rows[0][0]) == 0 else 0

        try:
            self.c.execute(
                "INSERT INTO voice (purpose, name, template, active, journal_id) VALUES (?, ?, ?, ?, ?)",
                [purpose, name, template, active, jid],
            )
        except Exception as e:
            # Unique-index violation (same purpose+name+scope).
            raise VoiceConflict(str(e)) from e
        return self.get(purpose, name, journal)

    def update(
        self,
        purpose: str,
        name: str,
        template: str,
        journal: str | None = None,
    ) -> Voice:
        _ensure_purpose(purpose)
        if name == DEFAULT_NAME:
            raise VoiceConflict("cannot edit the built-in default; add a new voice instead")
        jid = JournalService(self.s).resolve(journal) if journal else None
        if jid is None:
            rs = self.c.execute(
                "UPDATE voice SET template = ? WHERE purpose = ? AND name = ? AND journal_id IS NULL",
                [template, purpose, name],
            )
        else:
            rs = self.c.execute(
                "UPDATE voice SET template = ? WHERE purpose = ? AND name = ? AND journal_id = ?",
                [template, purpose, name, jid],
            )
        if rs.rows_affected == 0:
            raise VoiceNotFound(purpose, name, journal)
        return self.get(purpose, name, journal)

    def use(
        self,
        purpose: str,
        name: str,
        journal: str | None = None,
    ) -> Voice:
        """Mark this voice active in its scope. Name == 'default' clears active in the scope."""
        _ensure_purpose(purpose)
        jid = JournalService(self.s).resolve(journal) if journal else None

        if name == DEFAULT_NAME:
            if jid is None:
                self.c.execute(
                    "UPDATE voice SET active = 0 WHERE purpose = ? AND journal_id IS NULL",
                    [purpose],
                )
            else:
                self.c.execute(
                    "UPDATE voice SET active = 0 WHERE purpose = ? AND journal_id = ?",
                    [purpose, jid],
                )
            return _default_voice(purpose, journal_slug=journal)

        # Validate it exists in this scope.
        self.get(purpose, name, journal)
        if jid is None:
            self.c.execute(
                "UPDATE voice SET active = 0 WHERE purpose = ? AND journal_id IS NULL",
                [purpose],
            )
            self.c.execute(
                "UPDATE voice SET active = 1 WHERE purpose = ? AND name = ? AND journal_id IS NULL",
                [purpose, name],
            )
        else:
            self.c.execute(
                "UPDATE voice SET active = 0 WHERE purpose = ? AND journal_id = ?",
                [purpose, jid],
            )
            self.c.execute(
                "UPDATE voice SET active = 1 WHERE purpose = ? AND name = ? AND journal_id = ?",
                [purpose, name, jid],
            )
        return self.get(purpose, name, journal)

    def delete(
        self,
        purpose: str,
        name: str,
        journal: str | None = None,
    ) -> bool:
        _ensure_purpose(purpose)
        if name == DEFAULT_NAME:
            raise VoiceConflict("cannot delete the built-in default")
        jid = JournalService(self.s).resolve(journal) if journal else None
        if jid is None:
            rs = self.c.execute(
                "DELETE FROM voice WHERE purpose = ? AND name = ? AND journal_id IS NULL",
                [purpose, name],
            )
        else:
            rs = self.c.execute(
                "DELETE FROM voice WHERE purpose = ? AND name = ? AND journal_id = ?",
                [purpose, name, jid],
            )
        return rs.rows_affected > 0

    # --- ask -----------------------------------------------------------------

    def craft_step(
        self,
        llm: LlmService,
        history: list[dict],
        purpose: str,
        journal: str | None = None,
        answer: str | None = None,
    ) -> CraftStep:
        _ensure_purpose(purpose)
        h = list(history)

        if not h:
            current = self.template_for(purpose, journal=journal)
            scope = f"journal '{journal}'" if journal else "global"
            sys_prompt = CRAFT_VOICE_PROMPT.format(
                purpose=purpose, scope=scope, current=current,
            )
            h.append({"role": "system", "content": sys_prompt})
            h.append({"role": "user", "content": "Help me craft this voice."})
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
            turn = llm.step(h, CRAFT_TOOLS)
            if turn.assistant_message:
                h.append(turn.assistant_message)

            if not turn.tool_calls:
                h.append({"role": "user", "content": "Use the tools (ask_user or submit_voice)."})
                continue

            for tc_raw in turn.assistant_message.get("tool_calls") or []:
                fn = tc_raw["function"]
                args = json.loads(fn.get("arguments") or "{}")
                if fn["name"] == "ask_user":
                    return CraftStep(history=h, question=args.get("question", ""))
                if fn["name"] == "submit_voice":
                    name = (args.get("name") or "").strip()
                    template = (args.get("template") or "").strip()
                    if not name or not template:
                        h.append({
                            "role": "tool",
                            "tool_call_id": tc_raw["id"],
                            "content": "error: name and template are both required",
                        })
                        break
                    try:
                        voice = self.add(purpose, name, template, journal=journal)
                    except (VoiceConflict, JournalNotFound, Exception) as e:
                        h.append({
                            "role": "tool",
                            "tool_call_id": tc_raw["id"],
                            "content": f"error: {e}",
                        })
                        break
                    h.append({
                        "role": "tool",
                        "tool_call_id": tc_raw["id"],
                        "content": f"created voice {purpose}/{voice.name}",
                    })
                    return CraftStep(history=h, done=True, result=voice)
                h.append({
                    "role": "tool",
                    "tool_call_id": tc_raw["id"],
                    "content": f"unknown tool: {fn['name']}",
                })

        raise RuntimeError("voice craft flow exceeded max iterations")
