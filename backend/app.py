import os
import json
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, send_from_directory, session, make_response
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection, init_db, IntegrityError
from fetcher import update_database, fetch_anime_by_country
from apscheduler.schedulers.background import BackgroundScheduler
from pywebpush import webpush, WebPushException, Vapid
from flask_compress import Compress
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import datetime
import threading
import time as _time
from functools import lru_cache
import hashlib
import secrets

def serialize_anime(row):
    d = dict(row)
    title_eng = d.get('title_english') or ''
    if title_eng.strip() and title_eng.strip().lower() != 'null':
        d['display_title'] = title_eng.strip()
    else:
        d['display_title'] = d.get('title', '')
    return d

app = Flask(__name__, static_folder='../frontend')
# FEATURE: Use environment secret with fallback to a persistent local key
def _get_persistent_secret():
    secret_file = os.path.join(os.path.dirname(__file__), '.secret_key')
    if os.path.exists(secret_file):
        with open(secret_file, 'r') as f:
            return f.read().strip()
    
    # Generate new persistent secret
    new_secret = secrets.token_hex(32)
    try:
        with open(secret_file, 'w') as f:
            f.write(new_secret)
    except Exception:
        # Fallback to dynamic but slightly more stable key if file write fails
        _local_id = os.environ.get('USER', os.environ.get('USERNAME', 'server'))
        return hashlib.sha256(f"{os.path.abspath(__file__)}{_local_id}".encode()).hexdigest()
    return new_secret

app.secret_key = os.environ.get('SECRET_KEY', _get_persistent_secret())

app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=365)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600  # Cache static files for 1 hour

# --- Last-seen throttle (write at most once per 60s per user) ---
_last_seen_cache = {}  # {user_id: last_write_epoch}
_last_seen_lock = threading.Lock()

@app.before_request
def update_last_seen():
    # FEATURE: Skip for static files and non-essential requests to prevent DB lock contention
    if request.path.startswith('/static/') or any(request.path.endswith(ext) for ext in ['.js', '.css', '.png', '.jpg', '.ico']):
        return

    if 'user_id' in session:
        uid = session['user_id']
        now_epoch = _time.monotonic()
        with _last_seen_lock:
            if now_epoch - _last_seen_cache.get(uid, 0) < 60:
                return  # Skip — written recently
            _last_seen_cache[uid] = now_epoch
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cursor.execute("UPDATE users SET last_seen = ? WHERE id = ?", (now, uid))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Non-critical Error: Could not update last_seen: {e}")
# FEATURE: Split Deployment Support (Render Backend + Vercel Frontend)
# Using regex to allow all Vercel subdomains and local development ports
import re
CORS(app, supports_credentials=True, origins=[
    re.compile(r"https://.*\.vercel\.app$"),
    re.compile(r"http://localhost:\d+$"),
    re.compile(r"http://127\.0\.0\.1:\d+$"),
    "https://aninews-system.onrender.com" # Allow itself
])

# Optimization & Security
Compress(app)
# Force HTTPS for public deployment, but allow local testing
is_prod = os.environ.get('ENVIRONMENT') == 'production'
Talisman(app, 
    content_security_policy=None, 
    force_https=is_prod,
    session_cookie_secure=is_prod,
    session_cookie_samesite='None' if is_prod else 'Lax'
) 
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["10000 per hour", "200 per minute"],
    storage_uri="memory://",
)

# Email/SMTP Configuration (Loaded from Environment Variables)
SMTP_SERVER = os.environ.get('SMTP_SERVER', "smtp.gmail.com")
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER') 
SMTP_PASS = os.environ.get('SMTP_PASS') 

from functools import wraps
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"status": "error", "message": "Login required"}), 401
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM users WHERE id = ?", (session['user_id'],))
        user = cursor.fetchone()
        conn.close()
        
        if not user or user['role'] != 'admin':
            return jsonify({"status": "error", "message": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function

def send_actual_email(to_email, subject, body):
    # FEATURE: Improved reliability with better logging and debug checks
    if not SMTP_USER or SMTP_USER == "your-email@gmail.com":
        print(f"SIMULATION: [EMAIL LOG] To: {to_email} | Subject: {subject}")
        return True
        
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.set_debuglevel(0) # Set to 1 for verbose SMTP logs
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        return True
    except smtplib.SMTPAuthenticationError:
        print(f"CRITICAL: SMTP Authentication failed for {SMTP_USER}. Check credentials.")
        return False
    except Exception as e:
        print(f"ERROR: Failed to send email to {to_email}: {e}")
        return False

# VAPID setup
VAPID_PRIVATE_KEY_PATH = os.path.join(os.path.dirname(__file__), 'private_key.pem')
VAPID_PUBLIC_KEY_PATH = os.path.join(os.path.dirname(__file__), 'public_key.pem')

def get_vapid_keys():
    if not os.path.exists(VAPID_PRIVATE_KEY_PATH):
        v = Vapid()
        v.generate_keys()
        v.save_key(VAPID_PRIVATE_KEY_PATH)
        v.save_public_key(VAPID_PUBLIC_KEY_PATH)
    
    with open(VAPID_PUBLIC_KEY_PATH, 'r') as f:
        public_key = f.read().replace('-----BEGIN PUBLIC KEY-----', '').replace('-----END PUBLIC KEY-----', '').replace('\n', '').strip()
    return public_key

# Database initialization
init_db()
PUBLIC_VAPID_KEY = get_vapid_keys()

def send_notifications(payload):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_json FROM subscriptions")
    subs = cursor.fetchall()
    
    for sub in subs:
        try:
            subscription_info = json.loads(sub['subscription_json'])
            webpush(
                subscription_info=subscription_info,
                data=json.dumps(payload),
                vapid_private_key=VAPID_PRIVATE_KEY_PATH,
                vapid_claims={"sub": "mailto:admin@example.com"}
            )
        except WebPushException as ex:
            print(f"WebPush error: {ex}")
            # If subscription expired/invalid, remove it
            if ex.response and ex.response.status_code == 410:
                cursor.execute("DELETE FROM subscriptions WHERE subscription_json = ?", (sub['subscription_json'],))
        except Exception as e:
            print(f"Error sending notification: {e}")
            
    conn.commit()
    conn.close()

# Scheduler
def scheduled_update():
    print("Running scheduled update...")
    # 1. Fetch trending general
    n1, u1 = update_database()
    
    # 2. Fetch trending Chinese (Donghua)
    n2, u2 = update_database(fetch_anime_by_country('CN'))
    
    # 3. Fetch trending Korean (Manhwa/Anime)
    n3, u3 = update_database(fetch_anime_by_country('KR'))
    
    # 4. Fetch trending Movies
    from fetcher import fetch_popular_movies
    n4, u4 = update_database(fetch_popular_movies())
    
    # 5. Fetch trending Adult Content
    from fetcher import fetch_adult_anime
    n5, u5 = update_database(fetch_adult_anime())
    
    # 6. Update previously 'Ongoing' anime to check if they have completed
    from fetcher import update_ongoing_anime
    n6, u6 = update_ongoing_anime()

    # 7. Fetch Brand New / Upcoming releases that aren't trending yet
    from fetcher import fetch_newly_released_anime, fetch_upcoming_anime
    n7, u7 = update_database(fetch_newly_released_anime())
    n8, u8 = update_database(fetch_upcoming_anime())
    
    total_new = n1 + n2 + n3 + n4 + n5 + n6 + n7 + n8
    total_updated = u1 + u2 + u3 + u4 + u5 + u6 + u7 + u8
    
    # 6. Check and send reminders for ongoing anime/movies
    check_and_send_reminders()

    if total_new > 0 or total_updated > 0:
        send_notifications({
            "title": "Anime List Updated!",
            "body": f"Found {total_new} new anime and {total_updated} updates.",
            "url": "/"
        })

def check_and_send_reminders():
    print("Checking for pending reminders...")
    # Force an update of the database to catch the latest airing info/breaks from AniList
    update_database() 
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Automatic Cleanup: Delete reminders for anime that are now "Completed"
    cursor.execute("""
        DELETE FROM reminders 
        WHERE anime_id IN (SELECT id FROM anime WHERE status = 'Completed')
    """)
    
    # 2. Get active reminders for ongoing anime
    # We only notify if the episode_current matches the last_notified_episode increment
    cursor.execute("""
        SELECT r.id as reminder_row_id, r.user_id, r.anime_id, r.last_notified_episode, 
               u.email, a.title, a.episodes_current, a.next_episode_date, a.status
        FROM reminders r
        JOIN users u ON r.user_id = u.id
        JOIN anime a ON r.anime_id = a.id
        WHERE a.status = 'Ongoing'
    """)
    reminders = cursor.fetchall()
    
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    
    for rem in reminders:
        try:
            # Check if there is a new episode available that we haven't notified about
            current_ep = rem['episodes_current'] or 0
            last_notified = rem['last_notified_episode'] or 0
            
            # If the current episode in the DB is greater than what we last notified
            if current_ep > last_notified:
                subject = f"📺 New Episode Alert: {rem['title']} Ep {current_ep} is Out!"
                body = f"Good news! Episode {current_ep} of '{rem['title']}' is now available. Watch it now on AniNews!"
                
                if send_actual_email(rem['email'], subject, body):
                    # Update the last_notified_episode to current
                    cursor.execute("UPDATE reminders SET last_notified_episode = ? WHERE id = ?", (current_ep, rem['reminder_row_id']))
                    print(f"Episode notification sent to {rem['email']} for {rem['title']} Ep {current_ep}")

            # Also check upcoming airing for the very next episode (Pre-airing alert)
            if rem['next_episode_date']:
                # Ensure air_date is aware. The DB usually stores in UTC or local, 
                # but AniList/Fetcher outputs are usually UTC.
                date_str = rem['next_episode_date']
                if 'Z' in date_str:
                    air_date = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:
                    # If naive, assume UTC for safety or use .fromisoformat(date_str).replace(tzinfo=datetime.timezone.utc)
                    air_date = datetime.datetime.fromisoformat(date_str).replace(tzinfo=datetime.timezone.utc)
                
                time_until = air_date - now
                
                # Pre-airing alert: 1 hour before
                if datetime.timedelta(minutes=0) <= time_until <= datetime.timedelta(minutes=60):
                    # Only send pre-airing if we haven't already notified about THIS specific upcoming ep
                    # (Simple check: if we haven't notified about current+1 yet)
                    target_ep = current_ep + 1
                    if last_notified < target_ep:
                         subject = f"⏱️ 1 Hour Left: {rem['title']} Episode {target_ep} Airing Soon!"
                         body = f"Get ready! Episode {target_ep} of '{rem['title']}' airs in about an hour. Stay tuned!"
                         send_actual_email(rem['email'], subject, body)
                
        except Exception as e:
            print(f"Error processing reminder for {rem['title']}: {e}")
            
    conn.commit()
    conn.close()

def scheduled_update_all():
    print("Running 12-hour full sync...")
    from fetcher import update_all_anime
    n, u = update_all_anime()
    if n > 0 or u > 0:
        send_notifications({
            "title": "Comprehensive Database Sync Complete",
            "body": f"Performed a deep sync. Found {n} new details and {u} comprehensive updates.",
            "url": "/"
        })

# ─── Scheduler guard: only run in 1 process to avoid AniList rate-limit ban ───
# Multi-worker gunicorn would spin up N schedulers without this guard.
if not os.environ.get('VERCEL'):
    scheduler = BackgroundScheduler(daemon=True)
    # Feature 1: Increased frequency to 6 hours for better data freshness
    scheduler.add_job(func=scheduled_update,     trigger='interval', hours=6,
                      id='scheduled_update',     replace_existing=True,
                      max_instances=1,            coalesce=True)
    scheduler.add_job(func=scheduled_update_all, trigger='interval', hours=12,
                      id='scheduled_update_all', replace_existing=True,
                      max_instances=1,            coalesce=True)
    # Under gunicorn: only start if this worker "won" the lock file
    if os.environ.get('SERVER_SOFTWARE', '').startswith('gunicorn'):
        _lock_path = '/tmp/aninews_scheduler.lock'
        try:
            _lock_fd = open(_lock_path, 'w')
            import fcntl
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # This worker acquired the lock — it runs the scheduler
            if not scheduler.running:
                scheduler.start()
            print('[Scheduler] Started in gunicorn worker', os.getpid())
        except (IOError, OSError):
            print('[Scheduler] Another worker already holds the scheduler lock — skipping')
    else:
        # Plain `python app.py` dev mode — always start
        if not scheduler.running:
            scheduler.start()
        print('[Scheduler] Started in dev mode')

# API Routes

# --- Simple TTL cache for anonymous anime list requests ---
# Keyed on the full query-string; expires after 30 seconds
_anime_cache = {}          # key -> (timestamp, response_data)
_ANIME_CACHE_TTL = 30      # seconds
_anime_cache_lock = threading.Lock()

def _get_cached(key):
    with _anime_cache_lock:
        entry = _anime_cache.get(key)
        if entry and (_time.monotonic() - entry[0]) < _ANIME_CACHE_TTL:
            return entry[1]
    return None

def _set_cached(key, data):
    with _anime_cache_lock:
        _anime_cache[key] = (_time.monotonic(), data)
        # Evict old entries if cache grows large
        if len(_anime_cache) > 200:
            oldest = min(_anime_cache, key=lambda k: _anime_cache[k][0])
            del _anime_cache[oldest]

def _invalidate_cache():
    with _anime_cache_lock:
        _anime_cache.clear()

@app.route('/api/anime', methods=['GET'])
def get_anime():
    cache_key = request.full_path
    cached = _get_cached(cache_key)
    if cached is not None:
        resp = make_response(cached)
        resp.headers['Content-Type'] = 'application/json'
        resp.headers['Cache-Control'] = f'public, max-age={_ANIME_CACHE_TTL}'
        return resp

    status_filter = request.args.get('status')
    search = request.args.get('search')
    country = request.args.get('country')
    category_raw = request.args.get('category')
    mode = request.args.get('mode', 'home')
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    is_watchlist = (mode == 'watchlist')

    conn = get_db_connection()
    params = []

    # Base Query - no DISTINCT (forces temp B-TREE sort)
    if is_watchlist:
        if 'user_id' not in session:
            conn.close()
            return jsonify([])
        base_select = "SELECT a.*, w.created_at as w_created_at FROM watchlist w JOIN anime a ON a.id = w.anime_id"
        where_clauses = ["w.user_id = ?", "a.is_approved = 1"]
        params.append(session['user_id'])
    else:
        base_select = "SELECT a.* FROM anime a"
        where_clauses = ["a.is_approved = 1"]

    # Category filter via EXISTS sub-query (avoids duplicate rows, uses index)
    if category_raw:
        categories = [c.strip() for c in category_raw.split(',') if c.strip()]
        if categories:
            placeholders = ",".join(["?" for _ in categories])
            where_clauses.append(f"""
                EXISTS (
                    SELECT 1 FROM anime_genres ag
                    JOIN genres g ON ag.genre_id = g.id
                    WHERE ag.anime_id = a.id AND g.genre_name IN ({placeholders})
                )
            """)
            params.extend(categories)

    # Status filter
    if status_filter:
        if status_filter.lower() == 'completed':
            where_clauses.append("a.status IN ('Completed', 'Released')")
        else:
            where_clauses.append("LOWER(a.status) = LOWER(?)")
            params.append(status_filter)
    elif mode.lower() == 'upcoming':
        where_clauses.append("LOWER(a.status) = 'upcoming'")
    elif not is_watchlist:
        where_clauses.append("a.status != 'Cancelled'")
        # Removal of release_date restriction to allow all popular titles (Classics, etc.) to show up.

    # Search filter — Feature 3: multi-token fuzzy search
    if search:
        # Tokenize: split on whitespace, deduplicate, drop single-char tokens
        tokens = list(dict.fromkeys(
            t for t in search.lower().split() if len(t) >= 2
        ))
        if tokens:
            token_clauses = []
            for _ in tokens:
                # FEATURE 1: search title_english and title_romaji too
                token_clauses.append("""
                    (
                        (a.is_adult = 0 AND (
                            LOWER(a.title) LIKE ? OR
                            LOWER(COALESCE(a.title_english,'')) LIKE ? OR
                            LOWER(COALESCE(a.title_romaji,'')) LIKE ? OR
                            LOWER(a.description) LIKE ? OR
                            LOWER(a.genres) LIKE ?
                        ))
                        OR (a.is_adult = 1 AND LOWER(a.title) LIKE ?)
                    )
                """)
                tok = f"%{_}%"
                params.extend([tok, tok, tok, tok, tok, tok])
            where_clauses.append(" AND ".join(token_clauses))
        else:
            where_clauses.append("1=0")  # Empty query after stripping returns nothing
    else:
        where_clauses.append("a.is_adult = 0")

    # Country filter
    if country:
        where_clauses.append("a.country = ?")
        params.append(country)

    query = f"{base_select} WHERE {' AND '.join(where_clauses)}"

    # Sorting - use indexed columns
    if mode == 'trending':
        query += " ORDER BY COALESCE(a.trending_rank, 9999) ASC, a.rating_score DESC"
    elif mode == 'home' and not search:
        # BUG 1 fix: Show ALL statuses on home, Ongoing first then Upcoming then Completed
        query += """
            ORDER BY
                CASE a.status
                    WHEN 'Ongoing'  THEN 1
                    WHEN 'Upcoming' THEN 2
                    ELSE 3
                END ASC,
                COALESCE(a.trending_rank, 9999) ASC,
                a.rating_score DESC,
                a.release_date DESC
        """
    elif is_watchlist:
        query += " ORDER BY w.created_at DESC"
    elif category_raw:
        # BUG 2 fix: Genre pages must show Ongoing first, not sort by release_date
        # (release_date DESC was pushing Upcoming to the top since their dates are in the future)
        query += """
            ORDER BY
                CASE a.status
                    WHEN 'Ongoing'  THEN 1
                    WHEN 'Upcoming' THEN 2
                    ELSE 3
                END ASC,
                COALESCE(a.trending_rank, 9999) ASC,
                a.rating_score DESC
        """
    else:
        # Default fallback (search results etc.)
        query += " ORDER BY COALESCE(a.trending_rank, 9999) ASC, a.rating_score DESC, a.release_date DESC"

    query += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = conn.cursor()
    cursor.execute(query, params)
    anime = [serialize_anime(row) for row in cursor.fetchall()]
    conn.close()

    result_json = json.dumps(anime)
    # Cache only anonymous, non-watchlist requests
    if not is_watchlist and 'user_id' not in session:
        _set_cached(cache_key, result_json)

    resp = make_response(result_json)
    resp.headers['Content-Type'] = 'application/json'
    resp.headers['Cache-Control'] = f'public, max-age={_ANIME_CACHE_TTL}'
    return resp

# BUG 2: Dedicated hero banner endpoint — Ongoing+trending with actual images
@app.route('/api/anime/hero', methods=['GET'])
def get_hero_anime():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Primary: Ongoing with images, sorted by trending rank
    cursor.execute("""
        SELECT id, title, title_english, description, poster_url, status, genres, rating_score, episodes_current, episodes_total
        FROM anime
        WHERE is_approved = 1
          AND is_adult = 0
          AND status = 'Ongoing'
          AND poster_url IS NOT NULL
          AND poster_url != ''
        ORDER BY COALESCE(trending_rank, 9999) ASC, rating_score DESC
        LIMIT 6
    """)
    heroes = [serialize_anime(r) for r in cursor.fetchall()]

    # Fallback: if fewer than 3 results, pad with top-rated any-status
    if len(heroes) < 3:
        existing_ids = [h['id'] for h in heroes] or [0]
        placeholders = ','.join('?' for _ in existing_ids)
        cursor.execute(f"""
            SELECT id, title, title_english, description, poster_url, status, genres, rating_score, episodes_current, episodes_total
            FROM anime
            WHERE is_approved = 1
              AND is_adult = 0
              AND poster_url IS NOT NULL
              AND poster_url != ''
              AND id NOT IN ({placeholders})
            ORDER BY COALESCE(trending_rank, 9999) ASC, rating_score DESC
            LIMIT ?
        """, existing_ids + [6 - len(heroes)])
        heroes += [serialize_anime(r) for r in cursor.fetchall()]

    conn.close()
    resp = make_response(json.dumps(heroes))
    resp.headers['Content-Type'] = 'application/json'
    resp.headers['Cache-Control'] = 'public, max-age=120'
    return resp

# Feature 1: Last-update tracker
_last_update_time = None

def _run_update_and_track():
    global _last_update_time
    scheduled_update()
    import datetime as _dt
    _last_update_time = _dt.datetime.now(_dt.timezone.utc).isoformat()

@app.route('/api/last-update', methods=['GET'])
def get_last_update():
    return jsonify({'last_update': _last_update_time})

# Feature 1: Run an immediate non-blocking sync on startup (after function defined)
# FEATURE: Added a 10s delay to prevent DB contention right at startup
def _delayed_sync():
    import time
    time.sleep(10)
    _run_update_and_track()

if not os.environ.get('VERCEL'):
    threading.Thread(target=_delayed_sync, daemon=True).start()

@app.route('/api/home/combined', methods=['GET'])
def get_home_combined():
    # Performance Optimization: Batch common home page requests into one
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Trending (Compact List)
    cursor.execute("""
        SELECT id, title, title_english, poster_url, rating_score, status, genres, episodes_current, episodes_total
        FROM anime WHERE is_approved = 1 AND is_adult = 0
        ORDER BY COALESCE(trending_rank, 9999) ASC, rating_score DESC LIMIT 10
    """)
    trending = [serialize_anime(r) for r in cursor.fetchall()]
    
    # 2. Ongoing (Scroll Row)
    cursor.execute("""
        SELECT id, title, title_english, poster_url, rating_score, status, genres, episodes_current, episodes_total
        FROM anime WHERE is_approved = 1 AND is_adult = 0 AND status = 'Ongoing'
        ORDER BY COALESCE(trending_rank, 9999) ASC, rating_score DESC LIMIT 20
    """)
    ongoing = [serialize_anime(r) for r in cursor.fetchall()]
    
    # 3. Completed (Scroll Row)
    cursor.execute("""
        SELECT id, title, title_english, poster_url, rating_score, status, genres, episodes_current, episodes_total
        FROM anime WHERE is_approved = 1 AND is_adult = 0 AND status IN ('Completed', 'Released')
        ORDER BY release_date DESC, rating_score DESC LIMIT 20
    """)
    completed = [serialize_anime(r) for r in cursor.fetchall()]
    
    conn.close()
    
    resp = make_response(jsonify({
        "trending": trending,
        "ongoing": ongoing,
        "completed": completed
    }))
    resp.headers['Cache-Control'] = 'public, max-age=120'
    return resp

@app.route('/api/anime/<int:anime_id>', methods=['GET'])
def get_anime_detail(anime_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM anime WHERE id = ?", (anime_id,))
    anime = cursor.fetchone()
    if not anime:
        conn.close()
        return jsonify({"status": "error", "message": "Anime not found"}), 404

    anime_dict = serialize_anime(anime)

    # Batch all sub-queries in one connection round-trip
    cursor.execute(
        "SELECT episode_number, episode_name, release_date FROM episodes "
        "WHERE anime_id = ? ORDER BY episode_number ASC", (anime_id,)
    )
    anime_dict['episodes_list'] = [dict(row) for row in cursor.fetchall()]

    cursor.execute(
        "SELECT g.genre_name FROM genres g "
        "JOIN anime_genres ag ON g.id = ag.genre_id WHERE ag.anime_id = ?",
        (anime_id,)
    )
    anime_dict['genres_list'] = [row['genre_name'] for row in cursor.fetchall()]

    cursor.execute(
        "SELECT platform_name, url FROM streaming_platforms WHERE anime_id = ?",
        (anime_id,)
    )
    anime_dict['streaming_platforms'] = [dict(row) for row in cursor.fetchall()]

    conn.close()
    resp = make_response(json.dumps(anime_dict))
    resp.headers['Content-Type'] = 'application/json'
    resp.headers['Cache-Control'] = 'public, max-age=60'
    return resp

@app.route('/api/anime/<int:anime_id>/related', methods=['GET'])
def get_related_anime(anime_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Optimized Query: Find anime with overlapping genres using the relational table
    # This avoids fetching all candidates into Python memory.
    cursor.execute("""
        SELECT a.id, a.title, a.title_english, a.poster_url, a.rating_score, a.status, a.genres, a.episodes_current, a.episodes_total,
               COUNT(ag_other.genre_id) as overlap_count
        FROM anime a
        JOIN anime_genres ag_target ON ag_target.anime_id = ?
        JOIN anime_genres ag_other ON ag_other.genre_id = ag_target.genre_id AND ag_other.anime_id = a.id
        WHERE a.id != ? 
          AND a.is_approved = 1 
          AND a.is_adult = 0
        GROUP BY a.id
        ORDER BY overlap_count DESC, a.rating_score DESC
        LIMIT 16
    """, (anime_id, anime_id))
    
    related = [serialize_anime(r) for r in cursor.fetchall()]

    # Pad with top-scored if fewer than 4
    if len(related) < 4:
        exclude_ids = [r['id'] for r in related] + [anime_id]
        placeholders = ','.join('?' for _ in exclude_ids)
        cursor.execute(f"""
            SELECT id, title, title_english, poster_url, rating_score, status, genres, episodes_current, episodes_total
            FROM anime
            WHERE is_approved = 1 
              AND is_adult = 0 
              AND id NOT IN ({placeholders})
            ORDER BY rating_score DESC
            LIMIT ?
        """, exclude_ids + [12 - len(related)])
        related += [serialize_anime(r) for r in cursor.fetchall()]

    conn.close()
    resp = make_response(json.dumps(related))
    resp.headers['Content-Type'] = 'application/json'
    resp.headers['Cache-Control'] = 'public, max-age=300'
    return resp

@app.route('/api/admin/anime/<int:anime_id>', methods=['DELETE'])
@admin_required
def delete_anime(anime_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Delete related data first
    cursor.execute("DELETE FROM anime_genres WHERE anime_id = ?", (anime_id,))
    cursor.execute("DELETE FROM streaming_platforms WHERE anime_id = ?", (anime_id,))
    cursor.execute("DELETE FROM episodes WHERE anime_id = ?", (anime_id,))
    cursor.execute("DELETE FROM watchlist WHERE anime_id = ?", (anime_id,))
    cursor.execute("DELETE FROM reminders WHERE anime_id = ?", (anime_id,))
    cursor.execute("DELETE FROM reviews WHERE anime_id = ?", (anime_id,))
    # Delete the anime itself
    cursor.execute("DELETE FROM anime WHERE id = ?", (anime_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Anime deleted successfully"})

@app.route('/api/admin/anime', methods=['GET'])
def get_admin_anime():
    search = request.args.get('search')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if search:
        cursor.execute("SELECT * FROM anime WHERE title LIKE ? ORDER BY created_at DESC", (f"%{search}%",))
    else:
        cursor.execute("SELECT * FROM anime ORDER BY created_at DESC")
        
    anime = [serialize_anime(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(anime)

@app.route('/api/admin/approve/<int:anime_id>', methods=['POST'])
@admin_required
def approve_anime(anime_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE anime SET is_approved = 1 WHERE id = ?", (anime_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/auth/register', methods=['POST'])
@limiter.limit("3 per hour")
def register():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    username = data.get('username') or email.split('@')[0] if email else None
    
    if not email or not password:
        return jsonify({"status": "error", "message": "Email and password required"}), 400
        
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (email, username, password) VALUES (?, ?, ?)", (email, username, hashed_password))
        conn.commit()
        return jsonify({"status": "success", "message": "User registered successfully"})
    except Exception: # Fallback for both DB types
        return jsonify({"status": "error", "message": "Email already exists or registration failed"}), 400
    finally:
        conn.close()

@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"status": "error", "message": "Email and password required"}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    conn.close()

    # Guard against unsupported hash algorithms (e.g. scrypt on LibreSSL/macOS Python 3.9)
    password_ok = False
    if user:
        try:
            password_ok = check_password_hash(user['password'], password)
        except Exception:
            password_ok = False

    if password_ok:
        session.permanent = True
        session['user_id'] = user['id']
        session['email'] = user['email']
        session['role'] = user['role']
        return jsonify({"status": "success", "user": {"email": user['email'], "role": user['role']}})
    
    return jsonify({"status": "error", "message": "Invalid email or password"}), 401

@app.route('/api/auth/forgot-password', methods=['POST'])
@limiter.limit("3 per hour")
def forgot_password():
    data = request.json
    email = data.get('email')
    if not email:
        return jsonify({"status": "error", "message": "Email is required"}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    
    if not user:
        # For security, don't reveal if user exists
        return jsonify({"status": "success", "message": "Check your email for reset instructions."})
    
    token = secrets.token_urlsafe(32)
    expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
    
    cursor.execute("UPDATE users SET reset_token = ?, reset_token_expiry = ? WHERE id = ?", (token, expiry, user['id']))
    conn.commit()
    conn.close()
    
    subject = "Password Reset Request - AniNews"
    reset_url = f"{request.host_url}login?token={token}"
    body = f"Click the link below to reset your password. The link will expire in 1 hour.\n\n{reset_url}"
    
    send_actual_email(email, subject, body)
    
    return jsonify({"status": "success", "message": "Check your email for reset instructions."})

@app.route('/api/auth/reset-password', methods=['POST'])
@limiter.limit("3 per hour")
def reset_password():
    data = request.json
    token = data.get('token')
    new_password = data.get('password')
    
    if not token or not new_password:
        return jsonify({"status": "error", "message": "Token and new password required"}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, reset_token_expiry FROM users WHERE reset_token = ?", (token,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid or expired token"}), 400
    
    # Check expiry
    expiry_str = user['reset_token_expiry']
    expiry = datetime.datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
    if expiry < datetime.datetime.now(datetime.timezone.utc):
        conn.close()
        return jsonify({"status": "error", "message": "Token has expired"}), 400
    
    hashed_password = generate_password_hash(new_password, method='pbkdf2:sha256')
    cursor.execute("UPDATE users SET password = ?, reset_token = NULL, reset_token_expiry = NULL WHERE id = ?", (hashed_password, user['id']))
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success", "message": "Password reset successful! You can now login."})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"status": "success"})

@app.route('/api/auth/me', methods=['GET'])
def get_me():
    if 'user_id' in session:
        return jsonify({"status": "success", "user": {"email": session['email'], "role": session.get('role', 'user')}})
    return jsonify({"status": "error", "message": "Not logged in"}), 401

@app.route('/api/reminders/gmail', methods=['POST'])
def add_gmail_reminder():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Login required"}), 401
    
    data = request.json
    anime_id = data.get('anime_id')
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check for duplicate
        cursor.execute("SELECT id FROM reminders WHERE user_id = ? AND anime_id = ?", (user_id, anime_id))
        if cursor.fetchone():
            return jsonify({"status": "success", "message": "Reminder already scheduled"})

        cursor.execute("INSERT INTO reminders (user_id, anime_id) VALUES (?, ?)", (user_id, anime_id))
        conn.commit()
        
        cursor.execute("SELECT * FROM anime WHERE id = ?", (anime_id,))
        anime = cursor.fetchone()
        
        # In a real app, this would be scheduled. For now, we simulate success.
        # subject = f"AniNews Reminder: {anime['title']} Release Day"
        # body = f"Your reminder for {anime['title']} is scheduled."
        
        return jsonify({"status": "success", "message": "Gmail reminder scheduled successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/calendar/<int:anime_id>.ics')
def get_calendar_event(anime_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM anime WHERE id = ?", (anime_id,))
    anime = cursor.fetchone()
    conn.close()
    
    if not anime:
        return "Anime not found", 404
        
    date = anime['next_episode_date'] or anime['release_date']
    if not date or date == 'TBA':
        return "Release date not available", 400
        
    import datetime
    try:
        start_dt = datetime.datetime.fromisoformat(date.replace('Z', '+00:00'))
    except:
        return "Invalid date format", 400
        
    end_dt = start_dt + datetime.timedelta(minutes=30)
    
    fmt = "%Y%m%dT%H%M%SZ"
    eventName = f"AniNews: {anime['title']} Update"
    description = f"Watch now: {request.host_url}detail.html?id={anime_id}"
    
    ics_content = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AniNews//Anime Reminders//EN",
        "BEGIN:VEVENT",
        f"SUMMARY:{eventName}",
        f"DTSTART:{start_dt.strftime(fmt)}",
        f"DTEND:{end_dt.strftime(fmt)}",
        f"DESCRIPTION:{description}",
        "BEGIN:VALARM",
        "TRIGGER:-PT15M",
        "ACTION:DISPLAY",
        "DESCRIPTION:Reminder",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR"
    ]
    
    from flask import Response
    return Response(
        "\r\n".join(ics_content),
        mimetype="text/calendar",
        headers={"Content-Disposition": f"inline; filename={anime_id}.ics"}
    )

@app.route('/api/admin/manual-add', methods=['POST'])
@admin_required
def manual_add():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    
    genres_str = data.get('genres', '')
    
    cursor.execute('''
        INSERT INTO anime (title, release_date, status, description, poster_url, genres, is_approved)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    ''', (data['title'], data['release_date'], data['status'], data['description'], data['poster_url'], genres_str))
    
    anime_id = cursor.lastrowid

    # Handle Genres relationally
    if genres_str:
        genres_list = [g.strip() for g in genres_str.split(',') if g.strip()]
        for g_name in genres_list:
            cursor.execute("SELECT id FROM genres WHERE genre_name = ?", (g_name,))
            g_row = cursor.fetchone()
            if g_row:
                cursor.execute("INSERT OR IGNORE INTO anime_genres (anime_id, genre_id) VALUES (?, ?)", (anime_id, g_row['id']))

    # Handle Streaming Link
    streaming_url = data.get('streaming_url')
    if streaming_url:
        platform_name = data.get('platform_name', 'Official Site')
        cursor.execute('''
            INSERT OR REPLACE INTO streaming_platforms (anime_id, platform_name, url)
            VALUES (?, ?, ?)
        ''', (anime_id, platform_name, streaming_url))

    conn.commit()
    conn.close()
    
    send_notifications({
        "title": "New Anime Added!",
        "body": f"{data['title']} has been added to the list.",
        "url": "/"
    })
    
    return jsonify({"status": "success"})

@app.route('/api/watchlist', methods=['POST', 'DELETE'])
def update_watchlist():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Login required"}), 401
    
    data = request.json
    anime_id = data.get('anime_id')
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if request.method == 'POST':
            try:
                cursor.execute("INSERT INTO watchlist (user_id, anime_id) VALUES (?, ?)", (user_id, anime_id))
                conn.commit()
                return jsonify({"status": "success", "message": "Added to My List"})
            except IntegrityError:
                return jsonify({"status": "success", "message": "Already in My List"})
        else:
            cursor.execute("DELETE FROM watchlist WHERE user_id = ? AND anime_id = ?", (user_id, anime_id))
            conn.commit()
            return jsonify({"status": "success", "message": "Removed from My List"})
    finally:
        conn.close()

@app.route('/api/watchlist/check/<int:anime_id>', methods=['GET'])
def check_watchlist(anime_id):
    if 'user_id' not in session:
        return jsonify({"in_watchlist": False})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM watchlist WHERE user_id = ? AND anime_id = ?", (session['user_id'], anime_id))
    exists = cursor.fetchone() is not None
    conn.close()
    return jsonify({"in_watchlist": exists})

@app.route('/api/subscribe', methods=['POST'])
def subscribe():
    subscription_info = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO subscriptions (subscription_json) VALUES (?)", (json.dumps(subscription_info),))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # Already subscribed
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/vapid-public-key', methods=['GET'])
def get_public_key():
    return jsonify({"publicKey": PUBLIC_VAPID_KEY})

@app.route('/api/reviews/<int:anime_id>', methods=['GET'])
def get_reviews(anime_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Check if anime is upcoming
    cursor.execute("SELECT status FROM anime WHERE id = ?", (anime_id,))
    anime = cursor.fetchone()
    if anime and anime['status'] == 'Upcoming':
        conn.close()
        return jsonify([]) # No reviews for upcoming
        
    cursor.execute('''
        SELECT r.*, COALESCE(u.username, u.email) as username 
        FROM reviews r 
        JOIN users u ON r.user_id = u.id 
        WHERE r.anime_id = ? 
        ORDER BY r.created_at DESC
    ''', (anime_id,))
    reviews = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(reviews)

@app.route('/api/reviews', methods=['POST'])
def add_review():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Login required"}), 401
    
    data = request.json
    anime_id = data.get('anime_id')
    rating = data.get('rating')
    comment = data.get('comment', '').strip()
    
    if not comment:
        return jsonify({"status": "error", "message": "Comment cannot be empty"}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if upcoming
    cursor.execute("SELECT status FROM anime WHERE id = ?", (anime_id,))
    anime = cursor.fetchone()
    if anime and anime['status'] == 'Upcoming':
        conn.close()
        return jsonify({"status": "error", "message": "Comments not enabled for upcoming anime"}), 403
        
    # Basic moderation: Check for spam links or repetitive text (mock)
    if "http" in comment or len(comment) > 1000:
         conn.close()
         return jsonify({"status": "error", "message": "Invalid comment content"}), 400

    cursor.execute('''
        INSERT INTO reviews (user_id, anime_id, rating, comment)
        VALUES (?, ?, ?, ?)
    ''', (session['user_id'], anime_id, rating, comment))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/admin/force-update', methods=['POST'])
@admin_required
def force_update():
    n1, u1 = update_database()
    n2, u2 = update_database(fetch_anime_by_country('CN'))
    n3, u3 = update_database(fetch_anime_by_country('KR'))
    from fetcher import fetch_popular_movies, update_ongoing_anime, fetch_newly_released_anime, fetch_upcoming_anime
    n4, u4 = update_database(fetch_popular_movies())
    n5, u5 = update_ongoing_anime()
    n6, u6 = update_database(fetch_newly_released_anime())
    n7, u7 = update_database(fetch_upcoming_anime())
    return jsonify({
        "status": "success",
        "new": n1 + n2 + n3 + n4 + n5 + n6 + n7,
        "updated": u1 + u2 + u3 + u4 + u5 + u6 + u7
    })

@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def get_admin_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Total Users
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    # Online Users (last 5 minutes)
    five_minutes_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)).isoformat()
    cursor.execute("SELECT COUNT(*) FROM users WHERE last_seen > ?", (five_minutes_ago,))
    online_users = cursor.fetchone()[0]
    
    # Total Anime
    cursor.execute("SELECT COUNT(*) FROM anime")
    total_anime = cursor.fetchone()[0]
    
    # Pending Approval
    cursor.execute("SELECT COUNT(*) FROM anime WHERE is_approved = 0")
    pending_anime = cursor.fetchone()[0]
    
    conn.close()
    return jsonify({
        "total_users": total_users,
        "online_users": online_users,
        "total_anime": total_anime,
        "pending_anime": pending_anime
    })

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def get_admin_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, username, role, last_seen, created_at FROM users ORDER BY last_seen DESC")
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(users)

# ─── Favicon ─── (BUG 3: avoids 404 on every page load)
_STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(_STATIC_DIR, 'favicon.ico',
                               mimetype='image/x-icon')

# Serve Frontend
@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/admin')
def serve_admin():
    return send_from_directory(app.static_folder, 'admin.html')

@app.route('/login')
def serve_login():
    return send_from_directory(app.static_folder, 'login.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory(app.static_folder, path)



@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory(app.static_folder, '404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Server error'}), 500

@app.after_request
def add_cache(response):
    if request.path.startswith('/api/anime'):
        response.cache_control.max_age = 300
    return response



@app.route('/api/debug/db')
def debug_db():
    try:
        migrate_requested = request.args.get('migrate') == '1'
        migration_result = None
        
        if migrate_requested:
            from database import DB_PATH, _migrate_data_to_pg
            conn = get_db_connection()
            try:
                _migrate_data_to_pg(DB_PATH, conn)
                migration_result = "Success"
            except Exception as e:
                migration_result = f"Failed: {str(e)}"
            finally:
                conn.close()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM anime")
        count = cursor.fetchone()
        
        cursor.execute("SELECT status, COUNT(*) as c FROM anime GROUP BY status")
        statuses = cursor.fetchall()
        
        db_type = "PostgreSQL" if os.environ.get('DATABASE_URL') else "SQLite"
        
        conn.close()
        return jsonify({
            "db_type": db_type,
            "total_anime": dict(count)['count'] if count else 0,
            "statuses": [dict(s) for s in statuses],
            "env_db_path": os.environ.get('DB_PATH'),
            "is_prod": is_prod,
            "migration_trigger_result": migration_result
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(port=port, host='0.0.0.0')
