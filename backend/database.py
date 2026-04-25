import sqlite3
import os
import re

# FEATURE: Support for PostgreSQL on Render/Heroku/etc.
DATABASE_URL = os.environ.get('DATABASE_URL')
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'anime.db'))

def get_db_connection():
    # Strictly use PostgreSQL if URL is provided (Production)
    if DATABASE_URL:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Render provides this automatically
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        # We wrap the connection to make it behave like sqlite3 for compatibility
        return PostgresCompatConnection(conn)
    else:
        # Fallback to SQLite for local development only
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

class PostgresCompatConnection:
    def __init__(self, conn):
        self.conn = conn
        # FEATURE: Enable autocommit to prevent "InFailedSqlTransaction" errors
        self.conn.autocommit = True
    
    def cursor(self):
        from psycopg2.extras import RealDictCursor
        return PostgresCompatCursor(self.conn.cursor(cursor_factory=RealDictCursor), self.conn)
    
    def commit(self):
        if not self.conn.autocommit:
            self.conn.commit()
    
    def rollback(self):
        if not self.conn.autocommit:
            self.conn.rollback()
    
    def close(self):
        self.conn.close()
        
    def execute(self, sql, params=()):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

class PostgresCompatCursor:
    def __init__(self, cursor, conn):
        self.cursor = cursor
        self.conn = conn
        self.lastrowid = None

    def execute(self, sql, params=()):
        # 1. Convert ? placeholders to %s for psycopg2
        sql = sql.replace('?', '%s')
        
        # 2. Convert SQLite specific syntax to Postgres
        sql = re.sub(r'\bAUTOINCREMENT\b', 'SERIAL', sql, flags=re.IGNORECASE)
        
        # INSERT OR IGNORE -> INSERT ... ON CONFLICT DO NOTHING
        if re.search(r'INSERT\s+OR\s+IGNORE\s+INTO', sql, flags=re.IGNORECASE):
            sql = re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO', 'INSERT INTO', sql, flags=re.IGNORECASE)
            if 'episodes' in sql.lower():
                sql += ' ON CONFLICT (anime_id, episode_number) DO NOTHING'
            elif 'anime' in sql.lower() and 'anilist_id' in sql.lower():
                sql += ' ON CONFLICT (anilist_id) DO NOTHING'
            elif 'genres' in sql.lower() and 'genre_name' in sql.lower():
                sql += ' ON CONFLICT (genre_name) DO NOTHING'
            elif 'anime_genres' in sql.lower():
                sql += ' ON CONFLICT (anime_id, genre_id) DO NOTHING'
            elif 'subscriptions' in sql.lower():
                sql += ' ON CONFLICT (subscription_json) DO NOTHING'
            elif 'ON CONFLICT' not in sql.upper():
                sql += ' ON CONFLICT DO NOTHING'

        # INSERT OR REPLACE -> INSERT ... ON CONFLICT (...) DO UPDATE ...
        if re.search(r'INSERT\s+OR\s+REPLACE\s+INTO', sql, flags=re.IGNORECASE):
            sql = re.sub(r'INSERT\s+OR\s+REPLACE\s+INTO', 'INSERT INTO', sql, flags=re.IGNORECASE)
            if 'streaming_platforms' in sql.lower():
                sql += ' ON CONFLICT (anime_id, platform_name) DO UPDATE SET url = EXCLUDED.url'
            elif 'watchlist' in sql.lower():
                sql += ' ON CONFLICT (user_id, anime_id) DO NOTHING'
            elif 'reminders' in sql.lower():
                sql += ' ON CONFLICT (user_id, anime_id) DO UPDATE SET last_notified_episode = EXCLUDED.last_notified_episode'
            elif 'ON CONFLICT' not in sql.upper():
                sql += ' ON CONFLICT DO NOTHING'

        # COLLATE NOCASE cleanup
        sql = re.sub(r'COLLATE\s+NOCASE', '', sql, flags=re.IGNORECASE)

        try:
            if 'INSERT INTO' in sql.upper() and 'RETURNING' not in sql.upper():
                self.cursor.execute(sql, params)
                try:
                    self.cursor.execute("SELECT lastval() AS last_id")
                    res = self.cursor.fetchone()
                    if res:
                        if isinstance(res, dict): self.lastrowid = res.get('last_id')
                        else: self.lastrowid = res[0]
                except:
                    pass
            else:
                self.cursor.execute(sql, params)
        except Exception as e:
            raise e

    def executemany(self, sql, params_list):
        for params in params_list:
            self.execute(sql, params)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def close(self):
        self.cursor.close()

    def __getattr__(self, name):
        return getattr(self.cursor, name)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Core tables with SERIAL primary keys for Postgres compatibility
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS anime (
            id SERIAL PRIMARY KEY,
            anilist_id INTEGER UNIQUE,
            title TEXT NOT NULL,
            title_english TEXT,
            title_romaji TEXT,
            poster_url TEXT,
            status TEXT,
            description TEXT,
            release_date TEXT,
            country TEXT DEFAULT 'JP',
            is_approved INTEGER DEFAULT 0,
            episodes_total INTEGER,
            episodes_current INTEGER,
            last_episode_number INTEGER,
            last_episode_name TEXT,
            next_episode_date TEXT,
            studio TEXT,
            rating_score REAL,
            rating_votes INTEGER,
            genres TEXT,
            trending_rank INTEGER,
            is_adult INTEGER DEFAULT 0,
            episodes_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Table migrations
    columns = [
        ('title_english', 'TEXT'), ('title_romaji', 'TEXT'), ('episodes_total', 'INTEGER'),
        ('episodes_current', 'INTEGER'), ('last_episode_number', 'INTEGER'),
        ('last_episode_name', 'TEXT'), ('next_episode_date', 'TEXT'), ('studio', 'TEXT'),
        ('rating_score', 'REAL'), ('rating_votes', 'INTEGER'), ('genres', 'TEXT'),
        ('trending_rank', 'INTEGER'), ('is_adult', 'INTEGER DEFAULT 0'), ('episodes_json', 'TEXT')
    ]
    for col_name, col_type in columns:
        try:
            cursor.execute(f"ALTER TABLE anime ADD COLUMN {col_name} {col_type}")
        except: pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS episodes (
            id SERIAL PRIMARY KEY,
            anime_id INTEGER,
            episode_number INTEGER,
            episode_name TEXT,
            release_date TEXT,
            UNIQUE(anime_id, episode_number)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS genres (
            id SERIAL PRIMARY KEY,
            genre_name TEXT UNIQUE NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS anime_genres (
            anime_id INTEGER,
            genre_id INTEGER,
            UNIQUE(anime_id, genre_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            username TEXT,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            last_seen TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watchlist (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            anime_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, anime_id)
        )
    ''')

    # Indexes for performance
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_list_home ON anime(is_approved, is_adult, status, release_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_list_trending ON anime(is_approved, is_adult, trending_rank)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_title_search ON anime(title)")
    except: pass
    
    conn.commit()
    conn.close()

    # --- AUTO-MIGRATION ---
    if DATABASE_URL:
        try:
            pg_conn = get_db_connection()
            pg_cursor = pg_conn.cursor()
            pg_cursor.execute("SELECT COUNT(*) as count FROM anime")
            count = pg_cursor.fetchone()
            if count and (dict(count)['count'] < 10):
                if os.path.exists(DB_PATH):
                    _migrate_data_to_pg(DB_PATH, pg_conn)
            pg_conn.close()
        except Exception as e:
            print(f"Migration check failed: {e}")

def _migrate_data_to_pg(sqlite_path, pg_conn):
    import sqlite3
    sl_conn = None
    try:
        sl_conn = sqlite3.connect(sqlite_path)
        sl_conn.row_factory = sqlite3.Row
        sl_cursor = sl_conn.cursor()
        
        # Migrate Anime
        pg_cursor = pg_conn.cursor()
        pg_cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'anime'")
        target_cols = [c['column_name'].lower() for c in pg_cursor.fetchall()]
        
        sl_cursor.execute("SELECT * FROM anime")
        rows = sl_cursor.fetchall()
        for row in rows:
            d = dict(row)
            cols = [c for c in d.keys() if c.lower() in target_cols]
            vals = [d[c] for c in cols]
            placeholders = ", ".join(["%s"] * len(cols))
            sql = f"INSERT INTO anime ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT (anilist_id) DO NOTHING"
            pg_cursor.execute(sql, vals)
        pg_conn.commit()
        
        # Force Visibility
        pg_cursor.execute("UPDATE anime SET is_approved = 1 WHERE is_approved IS NULL")
        pg_cursor.execute("UPDATE anime SET is_adult = 0 WHERE is_adult IS NULL")
        pg_conn.commit()
        print("Migration success!")
    except Exception as e:
        print(f"Migration error: {e}")
    finally:
        if sl_conn: sl_conn.close()

if DATABASE_URL:
    import psycopg2
    IntegrityError = psycopg2.Error
else:
    IntegrityError = sqlite3.IntegrityError
