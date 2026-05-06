# wamid — context for Claude

A personal-narrative CLI. Reads commits + freeform notes, rewrites them into plain language via an OpenAI-compatible LLM, stores everything in SQLite. Optional FastAPI surface lets a frontend (e.g. aliboyev.com) read or write through the same services.

Origin problem: engineer doing serious work in private repos, no time/inclination to perform on Twitter, invisible to the market as a result. Auto-narrating what gets shipped is the opposite of "build in public" performance — it's the work telling its own story. Built to be useful to anyone with the same shape of problem.

## architecture

Two transport layers (`commands/`, `api/`) over one services layer. Hard rule: services know nothing about typer / fastapi / rich / http — they take a `Session` (db client + config), call other services, return pydantic models. Adding a third transport (websocket, scheduled job, MCP server) means another sibling directory, never touching services.

```
wamid/
  commands/        # typer CLI. one file per resource. wiring + presentation only.
  api/             # optional FastAPI. routers per resource. same shape as commands/.
  services/        # the real surface. one module per data domain.
    session.py     # open_session() — the only place a db client is opened.
    journals.py    # JournalService (group resource)
    records.py     # RecordService (individual entries; was 'journal' table)
    projects.py    # ProjectService — full real-project metadata
    repos.py       # RepoService — tracked git working trees
    voices.py      # VoiceService — multi-variant prompts, scoped per journal
    digests.py     # DigestService — daily/weekly/monthly rollups
    llm.py         # LlmService — OpenAI-compatible client; complete/chat/step
  migrations/      # numbered .sql files. applied idempotently by `wamid init`.
  git.py           # subprocess wrapper. no Session, no LLM, no domain knowledge.
  config.py        # pydantic-settings (toml + env)
  db.py            # libsql client factory + migration runner
tests/             # pytest. 56 tests over the core services. fakes the LLM.
```

## key design decisions

- **CLI owns the schema.** `wamid init` runs migrations. `db.url` config flips between local sqlite, self-hosted sqld, or Turso — same code.
- **TOML is bootstrap-only.** Just db, llm, api config. Everything else (projects, journals, records, repos, voices, digests) lives in sqlite, managed via service methods. Portable: copy the db, you have everything.
- **Services are the only place business logic lives.** Slug resolution, voice fallback chain, dedupe by external_id, scan-and-log orchestration — all in services. Commands and routes are pure adapters: parse args, call service, format output, map errors.
- **Same orchestrator behind CLI and HTTP.** `RecordService.log` is called by `wamid log` and `POST /records`. `JournalService.delete` is called by `wamid journal delete` and `DELETE /journals/{slug}`. No logic duplication ever.
- **`--ask` is a tool-call loop.** The LLM drives the interview using `ask_user` and `submit_*` tools. The service exposes one stateless `*_step()` method; the CLI loops it; an HTTP transport could too with client-managed history (CLI is the only consumer today).
- **Voices are keyed by purpose, scoped to journal.** `template_for(purpose, journal)` resolves: journal-scoped active → global active → built-in default (Python constant). Adding a new LLM-driven feature = adding a `PURPOSES` entry + calling `template_for` from the consuming service.
- **Privacy by opt-in.** Only what passes through `wamid log` ever leaves the machine. No git scraping daemon.
- **Read-only mode + bearer-token auth on writes.** `[api] read_only = true` blocks all non-safe HTTP methods. `[api] write_token = "..."` requires `Authorization: Bearer <token>` for writes when set. CLI is unaffected — it always writes directly.

## data model (current schema, v8)

- **projects** — slug, name, description, tagline, homepage_url, repo_url, started_at, ended_at, tags (TEXT csv), featured, visibility, color, emoji, status, created_at.
- **journals** — slug, name, description, tagline, visibility, color, emoji, featured, created_at. Default journal seeded by migration; cannot be deleted.
- **records** — journal_id (NOT NULL), project_id (nullable), ts, text, summary, source (`commit|manual|ask`), source_meta (json), external_id (nullable, partial-unique). The "journal entry" primitive.
- **repos** — path UNIQUE, name, git_author, project_id (nullable). No commit cursor — scans use git's time-range queries and dedupe by `external_id = sha`.
- **voice** — purpose, name, template, active, journal_id (nullable; NULL = global). Two partial unique indexes for global vs scoped.
- **digests** — project_id (nullable), period, start_ts, end_ts, text. UNIQUE(project_id, period, start_ts).
- **schema_migrations** — version, applied_at.

App-level cascade: libsql_client opens a fresh sqlite connection per `execute()`, so `PRAGMA foreign_keys = ON` doesn't persist. Services with cascading deletes (`JournalService.delete`, `ProjectService.delete`) issue the dependent DELETEs explicitly.

## conventions

- Pydantic `BaseModel` for every row type returned by a service — FastAPI uses them as `response_model` directly.
- Service methods accept slugs, not ids, for cross-resource refs (e.g. `RecordService.add(project="wamid", journal="engineering")`). Resolution happens inside the service via `_resolve_project` / `JournalService.resolve`.
- Exceptions per resource: `ProjectNotFound`, `JournalNotFound`, `RepoNotFound`, `VoiceNotFound`, `VoiceConflict`, `DuplicateExternal`, etc. CLI maps them to red-text exits; API maps them to 4xx.
- All timestamps are unix seconds (integer).
- Slugs autogenerated from `name` if not given; `re.sub(r"[^a-zA-Z0-9]+", "-", ...)`.
- Migrations: numbered `NNNN_short_name.sql`. The runner strips `-- comments` before splitting on `;`.

## stack

- `typer` — CLI
- `pydantic-settings` — TOML + env config
- `httpx` — LLM API calls (OpenAI-compatible, with retry on transient failures)
- `libsql-client` — db (file / sqld / Turso, all the same client)
- `fastapi` + `uvicorn` — optional `[server]` extra
- `pytest` — `[dev]` extra; tests live in `tests/`

## status

In active personal use. Schema v8. CLI + API both stable. Future possible directions: per-journal digests (needs `journal_id` on digests table), tags as a join table for filterable queries, profile table for the frontend's "about me" section, MCP server transport.
