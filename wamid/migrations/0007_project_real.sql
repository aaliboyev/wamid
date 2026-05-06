-- Expand projects with the metadata a real project page needs.
-- visibility comes back to project (orthogonal to journal visibility).
-- Status enum widens; existing 'active'/'archived' rows are unaffected.

ALTER TABLE projects ADD COLUMN tagline TEXT;
ALTER TABLE projects ADD COLUMN homepage_url TEXT;
ALTER TABLE projects ADD COLUMN repo_url TEXT;
ALTER TABLE projects ADD COLUMN started_at INTEGER;
ALTER TABLE projects ADD COLUMN ended_at INTEGER;
ALTER TABLE projects ADD COLUMN tags TEXT;
ALTER TABLE projects ADD COLUMN featured INTEGER NOT NULL DEFAULT 0;
ALTER TABLE projects ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public';
ALTER TABLE projects ADD COLUMN color TEXT;
ALTER TABLE projects ADD COLUMN emoji TEXT;
