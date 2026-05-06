-- Promote 'journal' from a flat entry table to a group resource.
-- Old table 'journal' becomes 'records'. New 'journals' table holds groups.
-- Visibility moves from project to journal.

CREATE TABLE journals (
  id          INTEGER PRIMARY KEY,
  slug        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  description TEXT,
  visibility  TEXT NOT NULL DEFAULT 'public',
  created_at  INTEGER NOT NULL
);

INSERT INTO journals (slug, name, description, visibility, created_at)
VALUES ('default', 'Default', 'The default journal', 'public', CAST(strftime('%s', 'now') AS INTEGER));

CREATE TABLE records (
  id          INTEGER PRIMARY KEY,
  journal_id  INTEGER NOT NULL REFERENCES journals(id) ON DELETE CASCADE,
  project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  ts          INTEGER NOT NULL,
  text        TEXT NOT NULL,
  summary     TEXT NOT NULL,
  source      TEXT NOT NULL,
  source_meta TEXT NOT NULL DEFAULT '{}',
  external_id TEXT
);

INSERT INTO records (id, journal_id, project_id, ts, text, summary, source, source_meta, external_id)
SELECT id, (SELECT id FROM journals WHERE slug = 'default'),
       project_id, ts, text, summary, source, source_meta, external_id
FROM journal;

DROP TABLE journal;

CREATE INDEX records_ts          ON records(ts);
CREATE INDEX records_project     ON records(project_id, ts);
CREATE INDEX records_journal     ON records(journal_id, ts);
CREATE UNIQUE INDEX records_external_id ON records(external_id) WHERE external_id IS NOT NULL;

ALTER TABLE projects DROP COLUMN visibility;
