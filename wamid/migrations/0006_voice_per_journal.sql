-- Voices can now be scoped to a journal. NULL journal_id = global voice.
-- Lookup priority: journal-scoped active → global active → built-in default.

CREATE TABLE voice_new (
  id          INTEGER PRIMARY KEY,
  purpose     TEXT NOT NULL,
  name        TEXT NOT NULL,
  template    TEXT NOT NULL,
  active      INTEGER NOT NULL DEFAULT 0,
  journal_id  INTEGER REFERENCES journals(id) ON DELETE CASCADE
);

INSERT INTO voice_new (id, purpose, name, template, active, journal_id)
  SELECT id, purpose, name, template, active, NULL FROM voice;

DROP TABLE voice;
ALTER TABLE voice_new RENAME TO voice;

CREATE INDEX voice_purpose ON voice(purpose);
CREATE UNIQUE INDEX voice_global_unique
  ON voice(purpose, name) WHERE journal_id IS NULL;
CREATE UNIQUE INDEX voice_scoped_unique
  ON voice(purpose, name, journal_id) WHERE journal_id IS NOT NULL;
