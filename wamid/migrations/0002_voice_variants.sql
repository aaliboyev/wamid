-- Multiple voices per purpose. Composite (purpose, name) identity.
-- Drop+recreate is fine: no production data yet.

DROP TABLE voice;

CREATE TABLE voice (
  id        INTEGER PRIMARY KEY,
  purpose   TEXT NOT NULL,
  name      TEXT NOT NULL,
  template  TEXT NOT NULL,
  active    INTEGER NOT NULL DEFAULT 0,
  UNIQUE (purpose, name)
);

CREATE INDEX voice_purpose ON voice(purpose);
