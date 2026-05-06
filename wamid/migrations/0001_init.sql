-- wamid schema v1

CREATE TABLE projects (
  id           INTEGER PRIMARY KEY,
  slug         TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  description  TEXT,
  status       TEXT NOT NULL DEFAULT 'active',     -- active | archived | stealth
  visibility   TEXT NOT NULL DEFAULT 'public',     -- public | private
  created_at   INTEGER NOT NULL                    -- unix seconds
);

CREATE TABLE project_repos (
  id             INTEGER PRIMARY KEY,
  project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  path           TEXT NOT NULL,
  git_author     TEXT,
  last_seen_sha  TEXT,
  UNIQUE (project_id, path)
);

CREATE TABLE journal (
  id           INTEGER PRIMARY KEY,
  ts           INTEGER NOT NULL,
  project_id   INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  text         TEXT NOT NULL,                      -- raw input
  summary      TEXT NOT NULL,                      -- llm-rewritten, public-facing
  source       TEXT NOT NULL,                      -- commit | manual | ask
  source_meta  TEXT NOT NULL DEFAULT '{}'          -- json
);
CREATE INDEX journal_ts      ON journal(ts);
CREATE INDEX journal_project ON journal(project_id, ts);

CREATE TABLE digests (
  id          INTEGER PRIMARY KEY,
  project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,  -- null = global
  period      TEXT NOT NULL,                       -- day | week | month
  start_ts    INTEGER NOT NULL,
  end_ts      INTEGER NOT NULL,
  text        TEXT NOT NULL,
  UNIQUE (project_id, period, start_ts)
);

CREATE TABLE voice (
  id        INTEGER PRIMARY KEY,
  name      TEXT NOT NULL UNIQUE,
  template  TEXT NOT NULL,
  active    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE profile (
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL
);

-- schema_migrations is managed by the migration runner (db.py)
