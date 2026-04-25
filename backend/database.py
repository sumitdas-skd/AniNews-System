import sqlite3
import os
import re

# FEATURE: Support for PostgreSQL on Render/Heroku/etc.
DATABASE_URL = os.environ.get('DATABASE_URL')
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'anime.db'))

def get_db_connection():
    # If DATABASE_URL is present, we use PostgreSQL for persistence
    if DATABASE_URL:
        print(f"Connecting to PostgreSQL...")
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

        print(f"Connecting to SQLite: {DB_PATH}")
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
        # FEATURE: Enable autocommit to prevent "InFailedSqlTransaction" errors
        # This makes it behave more like SQLite for simple migrations/scripts
        self.conn.autocommit = True
    
    def cursor(self):
        from psycopg2.extras import RealDictCursor
        return PostgresCompatCursor(self.conn.cursor(cursor_factory=RealDictCursor), self.conn)
    
    def commit(self):
        # No-op if autocommit is on, prevents errors
        if not self.conn.autocommit:
            self.conn.commit()
    
    def rollback(self):
        # No-op if autocommit is on, prevents errors
        if not self.conn.autocommit:
            self.conn.rollback()
        else:
            # If autocommit is on, we can't rollback the "transaction" 
            # but we can try to clear the state if needed. 
            # Usually not necessary with autocommit.
            pass
    
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
                # Fallback to DO NOTHING if we don't know the keys
                sql += ' ON CONFLICT DO NOTHING'

        # COLLATE NOCASE -> (Postgres doesn't need this, use LOWER() or ILIKE instead)
        sql = re.sub(r'COLLATE\s+NOCASE', '', sql, flags=re.IGNORECASE)

        try:
            # Postgres: if it's an INSERT, we often want the ID back
            if 'INSERT INTO' in sql.upper() and 'RETURNING' not in sql.upper():
                # We can't easily add RETURNING to every query without knowing the table structure,
                # so we stick to the lastval() approach but make it more robust.
                self.cursor.execute(sql, params)
                try:
                    self.cursor.execute("SELECT lastval() AS last_id")
                    res = self.cursor.fetchone()
                    # In psycopg2, fetchone() returns a dict-like object
                    if res:
                        if isinstance(res, dict): self.lastrowid = res.get('last_id')
                        else: self.lastrowid = res[0]
                except:
                    pass
            else:
                self.cursor.execute(sql, params)
        except Exception as e:
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
            episodes_json TEXT,
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
        ('is_adult', 'INTEGER DEFAULT 0'),
        ('episodes_json', 'TEXT')
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_title_search ON anime(title)")
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
    except Exception as e:
        print(f"Index creation warning: {e}")
    
    conn.commit()
    conn.close()

    # --- AUTO-MIGRATION LOGIC ---
    # If we are on Postgres and it's empty, try to import from local SQLite file
    if DATABASE_URL:
        try:
            pg_conn = get_db_connection()
            pg_cursor = pg_conn.cursor()
            pg_cursor.execute("SELECT COUNT(*) as count FROM anime")
            count = pg_cursor.fetchone()
            if count and (dict(count)['count'] < 10):
                print("Postgres database is empty. Checking for local SQLite data to migrate...")
                if os.path.exists(DB_PATH):
                    print(f"Found local data at {DB_PATH}. Starting migration to Postgres...")
                    _migrate_data_to_pg(DB_PATH, pg_conn)
            pg_conn.close()
        except Exception as e:
            print(f"Migration check failed: {e}")

def _migrate_data_to_pg(sqlite_path, pg_conn):
    import sqlite3
    try:
        sl_conn = sqlite3.connect(sqlite_path)
        sl_conn.row_factory = sqlite3.Row
        sl_cursor = sl_conn.cursor()
        
        pg_cursor = pg_conn.cursor()
        
        # 1. Migrate Genres
        sl_cursor.execute("SELECT * FROM genres")
        for row in sl_cursor.fetchall():
            pg_cursor.execute("INSERT INTO genres (id, genre_name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (row['id'], row['genre_name']))
        
        # 2. Migrate Anime
        sl_cursor.execute("SELECT * FROM anime")
        anime_rows = sl_cursor.fetchall()
        print(f"Migrating {len(anime_rows)} anime records...")
        
        # Get target columns to avoid schema mismatch errors
        pg_cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'anime'")
        target_cols = [c['column_name'] for c in pg_cursor.fetchall()]
        
        for row in anime_rows:
            d = dict(row)
            # Only keep columns that exist in the target table
            cols = [c for c in d.keys() if c.lower() in target_cols]
            vals = [d[c] for c in cols]
            placeholders = ", ".join(["%s"] * len(cols))
            sql = f"INSERT INTO anime ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT (anilist_id) DO NOTHING"
            pg_cursor.execute(sql, vals)
            
        # 3. Migrate Episodes
        sl_cursor.execute("SELECT * FROM episodes")
        ep_rows = sl_cursor.fetchall()
        print(f"Migrating {len(ep_rows)} episode records...")
        for row in ep_rows:
            pg_cursor.execute("INSERT INTO episodes (anime_id, episode_number, episode_name, release_date) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", 
                             (row['anime_id'], row['episode_number'], row['episode_name'], row.get('release_date')))
                             
        # 4. Migrate Users
        sl_cursor.execute("SELECT * FROM users")
        user_rows = sl_cursor.fetchall()
        print(f"Migrating {len(user_rows)} user records...")
        for row in user_rows:
            d = dict(row)
            cols = list(d.keys())
            vals = [d[c] for c in cols]
            placeholders = ", ".join(["%s"] * len(cols))
            sql = f"INSERT INTO users ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT (email) DO NOTHING"
            pg_cursor.execute(sql, vals)

        pg_conn.commit()
        
        # 5. Fix NULL visibility flags that prevent anime from showing up
        pg_cursor.execute("UPDATE anime SET is_approved = 1 WHERE is_approved IS NULL")
        pg_cursor.execute("UPDATE anime SET is_adult = 0 WHERE is_adult IS NULL")
        pg_conn.commit()
        
        sl_conn.close()
        print("Migration to PostgreSQL completed successfully!")
    except Exception as e:
        print(f"ERROR during migration: {e}")

# Export IntegrityError for use in other files
if DATABASE_URL:
    import psycopg2
    IntegrityError = psycopg2.Error # Broadest catch for compatibility
else:
    IntegrityError = sqlite3.IntegrityError

if __name__ == '__main__':
    init_db()
    print("Database initialized.")
