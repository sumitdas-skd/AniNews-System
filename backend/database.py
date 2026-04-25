import sqlite3
import os
import re

# FEATURE: Support for PostgreSQL on Render/Heroku/etc.
DATABASE_URL = os.environ.get('DATABASE_URL')
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'anime.db'))

def get_db_connection():
    if DATABASE_URL:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Parse DATABASE_URL if it's a standard postgres:// or postgresql:// URL
        # Render provides this automatically
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        # We wrap the connection to make it behave like sqlite3
        return PostgresCompatConnection(conn)
    else:
        # Ensure the directory exists if a custom path is provided
        db_dir = os.path.dirname(DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        # FEATURE: Increase timeout to 30s to handle concurrent write locks better
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        # Performance pragmas applied per-connection
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-65536")   # 64 MB page cache
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=268435456")  # 256 MB memory-mapped I/O
        conn.execute("PRAGMA busy_timeout = 30000") # 30s busy timeout
        return conn

class PostgresCompatConnection:
    def __init__(self, conn):
        self.conn = conn
    
    def cursor(self):
        from psycopg2.extras import RealDictCursor
        return PostgresCompatCursor(self.conn.cursor(cursor_factory=RealDictCursor), self.conn)
    
    def commit(self):
        self.conn.commit()
    
    def rollback(self):
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
        # 1. Convert ? placeholders to %s
        sql = sql.replace('?', '%s')
        
        # 2. Convert SQLite specific syntax to Postgres
        # AUTOINCREMENT -> SERIAL
        sql = re.sub(r'\bAUTOINCREMENT\b', 'SERIAL', sql, flags=re.IGNORECASE)
        
        # INSERT OR IGNORE -> INSERT ... ON CONFLICT DO NOTHING
        if re.search(r'INSERT\s+OR\s+IGNORE\s+INTO', sql, flags=re.IGNORECASE):
            sql = re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO', 'INSERT INTO', sql, flags=re.IGNORECASE)
            # This is a bit risky but works for simple cases in this app
            if 'ON CONFLICT' not in sql.upper():
                sql += ' ON CONFLICT DO NOTHING'

        # INSERT OR REPLACE -> INSERT ... ON CONFLICT (...) DO UPDATE ...
        # (This app uses it for streaming_platforms and watchlist mostly)
        if re.search(r'INSERT\s+OR\s+REPLACE\s+INTO', sql, flags=re.IGNORECASE):
            sql = re.sub(r'INSERT\s+OR\s+REPLACE\s+INTO', 'INSERT INTO', sql, flags=re.IGNORECASE)
            if 'streaming_platforms' in sql.lower():
                sql += ' ON CONFLICT (anime_id, platform_name) DO UPDATE SET url = EXCLUDED.url'
            elif 'watchlist' in sql.lower():
                sql += ' ON CONFLICT (user_id, anime_id) DO NOTHING'
            elif 'reminders' in sql.lower():
                sql += ' ON CONFLICT (user_id, anime_id) DO UPDATE SET last_notified_episode = EXCLUDED.last_notified_episode'

        # COLLATE NOCASE -> (Postgres doesn't need this if using ILIKE, but we can just strip it)
        sql = re.sub(r'COLLATE\s+NOCASE', '', sql, flags=re.IGNORECASE)

        try:
            self.cursor.execute(sql, params)
            if 'RETURNING id' not in sql.upper() and ('INSERT' in sql.upper()):
                try:
                    self.cursor.execute("SELECT lastval()")
                    row = self.cursor.fetchone()
                    self.lastrowid = row['lastval'] if row else None
                except:
                    pass
        except Exception as e:
            # Re-raise with original SQL for debugging
            # print(f"Postgres SQL Error: {e}\nSQL: {sql}")
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
    
    # Anime table
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Migration: Add columns if they don't exist
    columns = [
        ('title_english', 'TEXT'),
        ('title_romaji', 'TEXT'),
        ('episodes_total', 'INTEGER'),
        ('episodes_current', 'INTEGER'),
        ('last_episode_number', 'INTEGER'),
        ('last_episode_name', 'TEXT'),
        ('next_episode_date', 'TEXT'),
        ('studio', 'TEXT'),
        ('rating_score', 'REAL'),
        ('rating_votes', 'INTEGER'),
        ('genres', 'TEXT'),
        ('trending_rank', 'INTEGER'),
        ('is_adult', 'INTEGER DEFAULT 0')
    ]
    
    for col_name, col_type in columns:
        try:
            cursor.execute(f"ALTER TABLE anime ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass 

    # Episodes table
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

    # Genre table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS genres (
            id SERIAL PRIMARY KEY,
            genre_name TEXT UNIQUE NOT NULL
        )
    ''')

    # Anime_Genre table (Relational)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS anime_genres (
            anime_id INTEGER,
            genre_id INTEGER,
            UNIQUE(anime_id, genre_id)
        )
    ''')
    
    # Seed predefined genres
    predefined_genres = [
        "Action & Adventure", "Slice of Life", "Fantasy", "Dark Fantasy", "Sci-Fi & Mecha", 
        "Romance", "Supernatural & Horror", "Sports", "Isekai", "Mahou Shoujo", 
        "Iyashikei", "Harem / Reverse Harem", "Ecchi"
    ]
    for genre in predefined_genres:
        cursor.execute("INSERT INTO genres (genre_name) VALUES (?) ON CONFLICT DO NOTHING", (genre,))
    
    # Subscriptions table for Push Notifications
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            subscription_json TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Reviews table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            anime_id INTEGER,
            rating INTEGER,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Users table
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

    # Migrations for existing tables
    migrations = [
        ("users", "role", "TEXT DEFAULT 'user'"),
        ("users", "username", "TEXT"),
        ("users", "last_seen", "TIMESTAMP"),
        ("users", "reset_token", "TEXT"),
        ("users", "reset_token_expiry", "TIMESTAMP"),
        ("reviews", "user_id", "INTEGER"),
        ("reminders", "last_notified_episode", "INTEGER DEFAULT 0")
    ]
    
    for table, col, type_def in migrations:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {type_def}")
        except Exception:
            pass
    
    # Reminders table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            anime_id INTEGER,
            last_notified_episode INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, anime_id)
        )
    ''')

    # Watchlist table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watchlist (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            anime_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, anime_id)
        )
    ''')

    # Streaming Platforms table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS streaming_platforms (
            id SERIAL PRIMARY KEY,
            anime_id INTEGER,
            platform_name TEXT,
            url TEXT,
            UNIQUE(anime_id, platform_name)
        )
    ''')
    
    # Indexes (Postgres handles IF NOT EXISTS)
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_status ON anime(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_country ON anime(country)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_is_approved ON anime(is_approved)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_trending ON anime(trending_rank)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_anime ON reviews(anime_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_anime ON episodes(anime_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_list_home ON anime(is_approved, is_adult, status, release_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_list_trending ON anime(is_approved, is_adult, trending_rank)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_rating ON anime(rating_score)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_user ON reviews(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_anime ON watchlist(anime_id)")
    except Exception:
        pass
    
    conn.commit()
    conn.close()

# Export IntegrityError for use in other files
if DATABASE_URL:
    import psycopg2
    IntegrityError = psycopg2.Error # Broadest catch for compatibility
else:
    IntegrityError = sqlite3.IntegrityError

if __name__ == '__main__':
    init_db()
    print("Database initialized.")
