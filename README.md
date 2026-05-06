# wamid

**what am i doing** — a personal-narrative CLI. Logs your work (commits + freeform notes), rewrites it into plain language via a local LLM, and stores everything in SQLite. Whatever frontend you point at the same db renders your "right now" page.

## why

Engineers who don't perform on Twitter are invisible. Their work — often the most interesting work in the room — doesn't reach anyone who isn't already looking. The fix isn't "tweet more." The fix is letting the work narrate itself.

`wamid` is the deliberate gate: nothing leaves your machine unless it passes through `wamid log`. No scrapers, no daemons.

## concepts

- **project** — what you're building. Real metadata: tagline, homepage, repo, started/ended dates, tags, visibility, color, emoji, status (`planning|active|shipped|paused|archived`).
- **journal** — a stream of records (e.g. `engineering-log`, `notes`). Each has its own visibility and visual identity. Records belong to one journal; the default is seeded for you.
- **record** — an individual logged entry. Created from a commit (auto-summarized) or freeform text.
- **repo** — a tracked git working tree. Optionally attached to a project. Optionally filtered by author. Used by the commit scanner.
- **voice** — a system prompt template the LLM uses for a specific *purpose* (e.g. `journal.summarize`, `digest.day`, `project.ask`). Multi-variant. Voices can be **scoped to a journal**, so your engineering log can read formal while your notes journal stays casual.
- **digest** — daily / weekly / monthly summary regenerated from records via the matching `digest.{period}` voice.

## quick start

```sh
# install
git clone https://github.com/aaliboyev/wamid && cd wamid
uv sync                          # CLI only
uv sync --extra server           # + FastAPI for the read API

# bootstrap config (~/.wamid/config.toml) and db
uv run wamid init

# register a project and the repos it lives in
uv run wamid project add "Wamid" --tagline "the work tells its own story" \
    --emoji "📓" --tags "cli,python,llm" --featured
uv run wamid repo add ~/projects/personal/wamid --project wamid --author abror

# log a freeform thought (LLM rewrites it for plain readers)
uv run wamid log "shipped multi-variant voices and journal grouping"

# scan tracked repos for new commits
uv run wamid log                            # interactive, default last 24h
uv run wamid log --since "1 week ago" --auto  # cron / git-hook

# see what landed
uv run wamid recent
uv run wamid record show 1                  # raw text + LLM summary side by side

# roll up
uv run wamid digest generate --period day

# tune the voice for a specific journal
uv run wamid journal add "Engineering" --emoji "🛠️" --color "#5b8def"
uv run wamid voice add journal.summarize formal --journal engineering --ask
```

## the optional HTTP API

```sh
uv run wamid serve --port 8000
# GET /projects, GET /journals, GET /records?journal=engineering&limit=50,
# GET /digests, GET /repos, plus full CRUD on writes.
```

Config knobs (`~/.wamid/config.toml` or `WAMID_*` env):

```toml
[db]
url = "file:~/.wamid/wamid.db"   # or libsql://... or http://localhost:8080 (sqld)

[llm]
endpoint = "https://your-ollama-or-relay/v1"   # any OpenAI-compatible endpoint
model = "gemma4:e4b-it-q4_K_M"
api_key = ""
timeout_s = 300

[api]
read_only = false                 # block all writes when true (deploy as a public mirror)
write_token = ""                  # if set, writes require `Authorization: Bearer <token>`
```

`GET /health` reports `{"ok": true, "read_only": ..., "auth_required": ...}` so the frontend knows the deployment's mode.

## architecture

```
wamid/
  commands/    # typer CLI — wiring + presentation only
  api/         # optional FastAPI routes — same shape as commands/
  services/    # framework-agnostic business logic. one module per resource.
  migrations/  # numbered .sql files, applied idempotently by `wamid init`
  config.py    # pydantic-settings (toml + env)
  db.py        # libsql client + migration runner
  git.py       # subprocess wrapper for `git log`
```

**Hard rule:** services know nothing about typer / fastapi / rich / http. They take a `Session` (db client + config) and return pydantic models. Both the CLI and the API are thin adapters over the same services. Adding a new transport later (websocket? gRPC? scheduled job?) is one more directory beside `commands/` and `api/`.

The orchestration entry points (`RecordService.log_commit`, `ProjectService.ask_step`, `VoiceService.craft_step`, `DigestService.generate`) are called by both layers. CLI and API never duplicate logic.

## status

In active use. Schema at v8. 56-test pytest suite over the core services. CLI + API both stable for personal use. Deploy story is "run `wamid serve` somewhere" — no docker, no helm, no.

## license

MIT — see `LICENSE`.
