PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, login TEXT NOT NULL, login_key TEXT UNIQUE NOT NULL,
 password_hash TEXT NOT NULL, created_at TEXT NOT NULL, last_login TEXT,
 is_admin INTEGER NOT NULL DEFAULT 0 CHECK(is_admin IN (0,1)),
 style TEXT NOT NULL DEFAULT 'green' CHECK(style IN ('green','lilac','night'))
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires INTEGER NOT NULL, admin_open INTEGER NOT NULL DEFAULT 0 CHECK(admin_open IN (0,1))
);
CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 text TEXT NOT NULL, sender TEXT NOT NULL CHECK(sender IN ('user','support')), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 action TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 date TEXT NOT NULL, score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 10),
 note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS messages_user ON messages(user_id,id);
CREATE INDEX IF NOT EXISTS activity_user ON activity(user_id,id);
