-- Application tables (LangGraph checkpoints live in their own tables created by PostgresSaver.setup(),
-- reference vectors in ref_embeddings created by app.rag.index).

CREATE TABLE IF NOT EXISTS reports (
  report_id              text PRIMARY KEY,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  status                 text NOT NULL,                -- detecting | awaiting_review | approved | edited | rejected | failed
  store_code             text NOT NULL DEFAULT '',
  store_name             text NOT NULL DEFAULT '',
  route_code             text NOT NULL DEFAULT '',
  agent_id               text NOT NULL DEFAULT '',
  source                 text NOT NULL DEFAULT 'api',
  photo_path             text,
  photo_sha256           text,
  photo_phash            text,
  prompt_version         text,
  verify_prompt_version  text,
  config_id              text,
  models                 text,
  total_units            int,
  unknown_units          int,
  needs_review_units     int,
  overall_confidence     real,
  low_confidence         boolean,
  cost_usd               numeric(10,5),
  latency_s              real,
  reject_reason          text,
  flags                  jsonb NOT NULL DEFAULT '[]',
  review                 jsonb,
  body                   jsonb NOT NULL DEFAULT '{}'   -- report + boxes for the UI
);
CREATE INDEX IF NOT EXISTS reports_store ON reports (store_code, created_at DESC);
CREATE INDEX IF NOT EXISTS reports_status ON reports (status);
CREATE INDEX IF NOT EXISTS reports_phash ON reports (photo_phash);

-- One row per (shelf, brand, subtype, format) group — the customer's report format (n8n report_rows / Лист1).
CREATE TABLE IF NOT EXISTS report_rows (
  id                 bigserial PRIMARY KEY,
  report_id          text NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
  report_date        timestamptz NOT NULL DEFAULT now(),
  route_code         text NOT NULL DEFAULT '',
  store_code         text NOT NULL DEFAULT '',
  store_name         text NOT NULL DEFAULT '',
  product_name       text NOT NULL,
  product_subtype    text,
  package_format     text,
  shelf_index        int NOT NULL,
  position           text,
  front_facing_count int NOT NULL,
  needs_review       boolean NOT NULL DEFAULT false,
  status             text NOT NULL,                  -- на_проверке | утверждено | исправлено
  synced             boolean NOT NULL DEFAULT false  -- exported to Google Sheets
);
CREATE INDEX IF NOT EXISTS report_rows_report ON report_rows (report_id);
CREATE INDEX IF NOT EXISTS report_rows_sync ON report_rows (synced) WHERE NOT synced;

-- Route sheet: the agent sees only today's stores of his route (BACKLOG №26), not 6000.
CREATE TABLE IF NOT EXISTS stores (
  store_code  text PRIMARY KEY,           -- 8-digit code from the customer's system (00-0007xxx)
  store_name  text NOT NULL,
  address     text NOT NULL DEFAULT '',
  route_code  text NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS agents (
  agent_id          text PRIMARY KEY,
  name              text NOT NULL DEFAULT '',
  phone             text NOT NULL DEFAULT '',  -- normalised 7XXXXXXXXXX
  route_code        text NOT NULL DEFAULT '',
  telegram_user_id  bigint UNIQUE,
  role              text NOT NULL DEFAULT 'agent'  -- agent | supervisor | admin
);
