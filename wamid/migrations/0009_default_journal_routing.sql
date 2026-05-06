-- Optional journal routing: a project can declare a primary journal,
-- and a repo can override per-repo. Resolution order at log time:
-- explicit flag → repo.journal → project.primary_journal → 'default'.

ALTER TABLE projects ADD COLUMN primary_journal_id INTEGER REFERENCES journals(id) ON DELETE SET NULL;
ALTER TABLE repos    ADD COLUMN journal_id         INTEGER REFERENCES journals(id) ON DELETE SET NULL;
