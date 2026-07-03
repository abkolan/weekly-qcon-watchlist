CREATE TABLE IF NOT EXISTS historical_crawl_state (
  source_url TEXT PRIMARY KEY,
  year INTEGER NOT NULL,
  source_name TEXT NOT NULL,
  status TEXT NOT NULL,
  row_count INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  attempted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_historical_crawl_state_year_status
ON historical_crawl_state(year, status);
