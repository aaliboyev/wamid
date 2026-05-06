-- Repos as first-class resources, no commit cursor (time-range scans instead).
-- Repos may exist without a project (projectless / orphan).

DROP TABLE project_repos;

CREATE TABLE repos (
  id          INTEGER PRIMARY KEY,
  path        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  git_author  TEXT,
  project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  created_at  INTEGER NOT NULL
);

CREATE INDEX repos_project ON repos(project_id);
