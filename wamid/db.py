import time
from pathlib import Path

import libsql_client

from .config import Config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _resolve_url(url: str) -> str:
    # expand ~ for local file urls
    if url.startswith("file:"):
        path = url[len("file:") :]
        return "file:" + str(Path(path).expanduser())
    return url


def client(cfg: Config) -> libsql_client.Client:
    url = _resolve_url(cfg.db.url)
    # Note: libsql_client opens a fresh sqlite connection per execute(), so
    # PRAGMA foreign_keys=ON wouldn't persist. Services that need cascading
    # behavior do it explicitly (e.g. JournalService.delete).
    if url.startswith("file:"):
        path = url[len("file:") :]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return libsql_client.create_client_sync(url=url)
    return libsql_client.create_client_sync(url=url, auth_token=cfg.db.token or None)


def _applied_versions(c: libsql_client.Client) -> set[int]:
    c.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
    )
    rs = c.execute("SELECT version FROM schema_migrations")
    return {int(row[0]) for row in rs.rows}


def _discover_migrations() -> list[tuple[int, Path]]:
    out = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(p.name.split("_", 1)[0])
        out.append((version, p))
    return out


def migrate(c: libsql_client.Client) -> list[int]:
    applied = _applied_versions(c)
    ran: list[int] = []
    for version, path in _discover_migrations():
        if version in applied:
            continue
        sql = path.read_text()
        # Strip line comments before splitting so `;` inside `-- ...` doesn't break statements.
        cleaned = "\n".join(
            line.split("--", 1)[0] for line in sql.splitlines()
        )
        statements = [s.strip() for s in cleaned.split(";") if s.strip()]
        for stmt in statements:
            c.execute(stmt)
        c.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            [version, int(time.time())],
        )
        ran.append(version)
    return ran
