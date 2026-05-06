-- Repos can now carry their own description, which the LLM uses as context
-- when summarizing commits ("here's what this codebase is, in plain language").

ALTER TABLE repos ADD COLUMN description TEXT;
