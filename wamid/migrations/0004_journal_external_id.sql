-- external_id holds a source-system identifier (e.g. a git commit sha) so that
-- repeated scans don't double-log. Nullable: only set for sources that have one.

ALTER TABLE journal ADD COLUMN external_id TEXT;

CREATE UNIQUE INDEX journal_external_id
  ON journal(external_id)
  WHERE external_id IS NOT NULL;
