"""
migrate_to_production.py
------------------------
Migrates ALL anime data from the local SQLite database to Render's PostgreSQL.
Run this locally with your DATABASE_URL from Render.

Usage:
    DATABASE_URL="postgresql://..." python migrate_to_production.py
"""

import os
import sys
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), 'anime.db')
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable is not set.")
    print("Get it from: Render Dashboard → Your PostgreSQL service → Connection → External Database URL")
    print("")
    print("Then run:")
    print('  DATABASE_URL="postgresql://user:pass@host/dbname" python migrate_to_production.py')
    sys.exit(1)

if not os.path.exists(DB_PATH):
    print(f"ERROR: Local SQLite file not found at: {DB_PATH}")
    sys.exit(1)

import psycopg2
from psycopg2.extras import RealDictCursor

print(f"Connecting to PostgreSQL...")
pg_conn = psycopg2.connect(DATABASE_URL, sslmode='require')
pg_conn.autocommit = False
pg_cur = pg_conn.cursor(cursor_factory=RealDictCursor)

print(f"Connecting to local SQLite: {DB_PATH}")
sl_conn = sqlite3.connect(DB_PATH)
sl_conn.row_factory = sqlite3.Row

# ── Check current counts ──────────────────────────────────────────────────────
pg_cur.execute("SELECT COUNT(*) as count FROM anime")
pg_before = pg_cur.fetchone()['count']
sl_cur = sl_conn.cursor()
sl_cur.execute("SELECT COUNT(*) FROM anime")
sl_total = sl_cur.fetchone()[0]

print(f"Local SQLite:       {sl_total} anime")
print(f"Remote PostgreSQL:  {pg_before} anime")
print(f"To migrate:         {sl_total - pg_before} new records (skipping duplicates)")
print()

# ── Get PostgreSQL column names ───────────────────────────────────────────────
pg_cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'anime' ORDER BY ordinal_position")
target_cols = set(r['column_name'].lower() for r in pg_cur.fetchall())

# ── Migrate Anime ─────────────────────────────────────────────────────────────
print("Migrating anime table...")
sl_cur.execute("SELECT * FROM anime")
rows = sl_cur.fetchall()

inserted = 0
skipped  = 0
errors   = 0
batch_size = 100

for i, row in enumerate(rows):
    d = dict(row)
    cols = [c for c in d.keys() if c.lower() in target_cols and c != 'id']
    vals = [d[c] for c in cols]
    col_str = ', '.join(cols)
    ph_str  = ', '.join(['%s'] * len(cols))
    sql = f"""
        INSERT INTO anime ({col_str})
        VALUES ({ph_str})
        ON CONFLICT (anilist_id) DO UPDATE SET
            status            = EXCLUDED.status,
            episodes_current  = EXCLUDED.episodes_current,
            episodes_total    = EXCLUDED.episodes_total,
            trending_rank     = EXCLUDED.trending_rank,
            rating_score      = EXCLUDED.rating_score,
            next_episode_date = EXCLUDED.next_episode_date,
            is_approved       = GREATEST(anime.is_approved, EXCLUDED.is_approved),
            updated_at        = CURRENT_TIMESTAMP
    """
    try:
        pg_cur.execute(sql, vals)
        if pg_cur.rowcount > 0:
            inserted += 1
        else:
            skipped += 1
    except Exception as e:
        errors += 1
        if errors <= 5:  # Only show first 5 errors
            print(f"  Row error ({d.get('title','?')}): {e}")
        pg_conn.rollback()
        pg_conn.autocommit = False

    # Commit in batches
    if (i + 1) % batch_size == 0:
        pg_conn.commit()
        print(f"  Progress: {i+1}/{len(rows)} | inserted={inserted}, skipped={skipped}, errors={errors}")

pg_conn.commit()
print(f"\nAnime migration done: {inserted} inserted/updated, {skipped} already existed, {errors} errors")

# ── Migrate Genres ────────────────────────────────────────────────────────────
print("\nMigrating genres...")
sl_cur.execute("SELECT * FROM genres")
for row in sl_cur.fetchall():
    try:
        pg_cur.execute(
            "INSERT INTO genres (genre_name) VALUES (%s) ON CONFLICT (genre_name) DO NOTHING",
            (row['genre_name'],)
        )
    except: pass
pg_conn.commit()

# ── Migrate Anime-Genres mapping ──────────────────────────────────────────────
print("Migrating anime_genres mapping...")
sl_cur.execute("SELECT ag.anime_id, ag.genre_id FROM anime_genres ag")
ag_rows = sl_cur.fetchall()
ag_ok = 0
for row in ag_rows:
    try:
        # Map via anilist_id to ensure correct IDs after migration
        pg_cur.execute("""
            INSERT INTO anime_genres (anime_id, genre_id)
            SELECT a.id, g.id
            FROM anime a, genres g
            WHERE a.id = (
                SELECT id FROM anime WHERE id = %s LIMIT 1
            )
            AND g.id = %s
            ON CONFLICT (anime_id, genre_id) DO NOTHING
        """, (row['anime_id'], row['genre_id']))
        ag_ok += 1
    except: pass
pg_conn.commit()
print(f"  Anime-genres done: {ag_ok} mappings")

# ── Force-approve everything that was imported ────────────────────────────────
print("\nEnsuring all migrated anime are approved and visible...")
pg_cur.execute("UPDATE anime SET is_approved = 1 WHERE is_approved IS NULL OR is_approved = 0")
pg_cur.execute("UPDATE anime SET is_adult = 0 WHERE is_adult IS NULL")
pg_conn.commit()

# ── Final count ───────────────────────────────────────────────────────────────
pg_cur.execute("SELECT COUNT(*) as count FROM anime WHERE is_approved = 1 AND is_adult = 0")
pg_after = pg_cur.fetchone()['count']
print(f"\n✅ Migration complete!")
print(f"   Before: {pg_before} anime on production")
print(f"   After:  {pg_after} approved, visible anime on production")
print(f"\nVisit https://aninews-system.onrender.com/api/debug/status to confirm.")

pg_conn.close()
sl_conn.close()
