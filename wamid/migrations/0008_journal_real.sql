-- Give journals their own visual identity on the frontend.

ALTER TABLE journals ADD COLUMN tagline TEXT;
ALTER TABLE journals ADD COLUMN color TEXT;
ALTER TABLE journals ADD COLUMN emoji TEXT;
ALTER TABLE journals ADD COLUMN featured INTEGER NOT NULL DEFAULT 0;
