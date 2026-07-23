-- Final Multi-Tenant SaaS Schema for Hermes Backlink Engine
-- Database: Postgres (Supabase)

CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT DEFAULT 'user',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_settings (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  min_score INTEGER DEFAULT 80,
  platforms TEXT DEFAULT '["reddit", "news"]',
  reminder_intervals_hours TEXT DEFAULT '{"standard":48, "strong":72, "archive":168}',
  ai_model TEXT DEFAULT 'vertex/gemini-3.1-flash-lite',
  schedule_frequency_minutes INTEGER DEFAULT 60,
  telegram_formatting TEXT DEFAULT '',
  business_thresholds TEXT DEFAULT '{}',
  learning_enabled INTEGER DEFAULT 1,
  last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  is_read INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS opportunities (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  url TEXT NOT NULL,
  title TEXT,
  platform TEXT,
  snippet TEXT,
  score_100 INTEGER,
  confidence INTEGER,
  business_impact TEXT,
  status TEXT DEFAULT 'PENDING',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  name TEXT NOT NULL,
  domain TEXT NOT NULL,
  target_keywords TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
