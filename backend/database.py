import sqlite3
import os

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'anime.db'))

def get_db_connection():
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

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Anime table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS anime (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        except sqlite3.OperationalError:
            pass 

    # Episodes table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anime_id INTEGER,
            episode_number INTEGER,
            episode_name TEXT,
            release_date TEXT,
            FOREIGN KEY (anime_id) REFERENCES anime (id),
            UNIQUE(anime_id, episode_number)
        )
    ''')

    # Genre table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS genres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            genre_name TEXT UNIQUE NOT NULL
        )
    ''')

    # Anime_Genre table (Relational)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS anime_genres (
            anime_id INTEGER,
            genre_id INTEGER,
            FOREIGN KEY (anime_id) REFERENCES anime (id),
            FOREIGN KEY (genre_id) REFERENCES genres (id),
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
        cursor.execute("INSERT OR IGNORE INTO genres (genre_name) VALUES (?)", (genre,))
    
    # Subscriptions table for Push Notifications
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subscription_json TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Reviews table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            anime_id INTEGER,
            rating INTEGER,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (anime_id) REFERENCES anime (id)
        )
    ''')
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        except sqlite3.OperationalError:
            pass
    
    # Reminders table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            anime_id INTEGER,
            last_notified_episode INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (anime_id) REFERENCES anime (id),
            UNIQUE(user_id, anime_id)
        )
    ''')

    # Watchlist table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            anime_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (anime_id) REFERENCES anime (id),
            UNIQUE(user_id, anime_id)
        )
    ''')

    # Streaming Platforms table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS streaming_platforms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anime_id INTEGER,
            platform_name TEXT,
            url TEXT,
            FOREIGN KEY (anime_id) REFERENCES anime (id),
            UNIQUE(anime_id, platform_name)
        )
    ''')
    
    # Indexes — simple
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_status ON anime(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_country ON anime(country)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_is_approved ON anime(is_approved)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_trending ON anime(trending_rank)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_anime ON reviews(anime_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_anime ON episodes(anime_id)")
    # Compound indexes that match the exact hot query patterns
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_list_home ON anime(is_approved, is_adult, status, release_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_list_trending ON anime(is_approved, is_adult, trending_rank)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_title_search ON anime(title COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_rating ON anime(rating_score)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_user ON reviews(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_anime ON watchlist(anime_id)")
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized.")
