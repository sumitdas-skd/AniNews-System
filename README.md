# 📺 AniNews - Ultimate Anime Tracker

AniNews is a modern, responsive web application for tracking the latest anime, trending shows, and upcoming releases. It features a sleek glassmorphic UI, real-time search, and automated data updates.

## ✨ Features
- **🔥 Trending Anime**: Live updates from AniList.
- **🔍 Fast Search**: Debounced search for instant results.
- **🔖 My List**: Personalized watchlist (Save for later).
- **🌗 Modern UI**: Fully responsive, high-end aesthetics.
- **⚙️ Admin Dashboard**: Manual anime management and update triggers.
- **📅 Smart Reminders**: System calendar integration and Email alerts.

---

## 🚀 Public Deployment
The easiest way to make this website public is using **Render.com**.

1. Connect your repo to Render.
2. Set **Build Command**: `pip install -r backend/requirements.txt`
3. Set **Start Command**: `gunicorn --chdir backend app:app`
4. Set **Environment Variables**:
   - `ENVIRONMENT`: `production` (Enforces HTTPS)
   - `DB_PATH`: `/opt/render/project/src/backend/data/anime.db` (For persistence)
   - `SECRET_KEY`: (Any long random string)

---

## 💻 Local Setup
1. **Clone the Repo**.
2. **Install Dependencies**:
   ```bash
   pip install -r backend/requirements.txt
   ```
3. **Run the Server**:
   ```bash
   python backend/app.py
   ```
4. **Access**: Open `http://localhost:5001`.

---

## 🛠️ Tech Stack
- **Frontend**: Vanilla JS, CSS (Glassmorphism), HTML5.
- **Backend**: Flask (Python), SQLite.
- **Worker**: APScheduler (Background data fetching).
- **APIs**: AniList GraphQL API.

---

## 🔒 Privacy & Safety
- **No Voice Recording**: All microphone/voice search features have been completely removed for maximum privacy.
- **Secure Auth**: Password hashing and cookie-based sessions.
- **Security Headers**: Powered by Flask-Talisman.
