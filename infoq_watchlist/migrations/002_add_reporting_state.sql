ALTER TABLE talks ADD COLUMN watch_status TEXT NOT NULL DEFAULT 'new';
ALTER TABLE talks ADD COLUMN last_reported_at TEXT;
ALTER TABLE talks ADD COLUMN issue_number INTEGER;
ALTER TABLE talks ADD COLUMN issue_url TEXT;
