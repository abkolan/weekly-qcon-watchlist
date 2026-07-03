ALTER TABLE talks ADD COLUMN github_issue_number INTEGER;
ALTER TABLE talks ADD COLUMN github_issue_url TEXT;
ALTER TABLE talks ADD COLUMN github_issue_node_id TEXT;
ALTER TABLE talks ADD COLUMN github_project_item_id TEXT;
ALTER TABLE talks ADD COLUMN last_synced_at TEXT;

UPDATE talks
SET github_issue_number = issue_number,
    github_issue_url = issue_url
WHERE github_issue_number IS NULL
  AND issue_number IS NOT NULL;
