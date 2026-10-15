CREATE TABLE IF NOT EXISTS inbox (
  id TEXT PRIMARY KEY,
  sealed TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS inbox_created ON inbox(created_at,id);
