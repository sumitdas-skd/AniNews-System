/* ═══════════════════════════════════════════
   ANINEWS — app.js  (Dark Sakura Cyberpunk)
   ═══════════════════════════════════════════ */

/* ─── Service Worker ─── */
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    });
}

// Removed global unhandledrejection listener to prevent false-positive toasts.
// All critical fetch calls (Anime, Auth, Hero) already have their own try/catch blocks.

/* ─── State ─── */
let currentMode = 'home';
let currentPage = 0;
let authCache   = null;          // null = unknown, true/false = known
let authCacheTs = 0;             // epoch ms when cache was set
const AUTH_CACHE_TTL = 30_000;   // 30 s — Improvement 4
let isRedirecting = false;       // BUG 7: prevents double redirect
const PAGE_SIZE = 20;
const genreList = [
    "Action & Adventure", "Slice of Life", "Fantasy", "Dark Fantasy", "Sci-Fi & Mecha",
    "Romance", "Supernatural & Horror", "Sports", "Isekai", "Mahou Shoujo",
    "Iyashikei", "Harem / Reverse Harem", "Ecchi"
];

// BUG 4: Map nav-tab display labels → exact AniList genre strings
const GENRE_API_MAP = {
    'Action':           'Action & Adventure',
    'Horror':           'Supernatural & Horror',
    'Sci-Fi':           'Sci-Fi & Mecha',
    'Dark Fantasy':     'Dark Fantasy',
    'Slice of Life':    'Slice of Life',
    'Mahou Shoujo':     'Mahou Shoujo',
};

let lastFetchId = 0;

// ─── Toast notification system (Improvement 2) ───
function showToast(msg, type = 'success') {
    let tray = document.getElementById('toastTray');
    if (!tray) {
        tray = document.createElement('div');
        tray.id = 'toastTray';
        tray.style.cssText = 'position:fixed;bottom:1.5rem;right:1.5rem;z-index:9999;display:flex;flex-direction:column;gap:0.5rem;pointer-events:none;';
        document.body.appendChild(tray);
    }
    const t = document.createElement('div');
    t.style.cssText = `
        background:${type === 'success' ? 'linear-gradient(135deg,#22c55e,#16a34a)' : 'linear-gradient(135deg,#ef4444,#dc2626)'};
        color:#fff;padding:0.75rem 1.25rem;border-radius:10px;
        font-family:'Outfit',sans-serif;font-size:0.875rem;font-weight:600;
        box-shadow:0 4px 20px rgba(0,0,0,0.4);
        animation:toastIn 0.3s ease;pointer-events:auto;
    `;
    t.textContent = msg;
    tray.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity 0.4s'; setTimeout(() => t.remove(), 400); }, 2800);
}

// inject toast keyframe once
(() => {
    const s = document.createElement('style');
    s.textContent = '@keyframes toastIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}';
    document.head.appendChild(s);
})();

/* ─── Hero Banner State ─── */
let heroAnimeData  = [];
let heroIndex      = 0;
let heroInterval   = null;

/* ─── Debounce ─── */
function debounce(fn, ms = 300) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn.apply(this, a), ms); };
}

/* FEATURE 1: Always prefer English title */
function getTitle(anime) {
    if (!anime) return '';
    const eng = anime.title_english || anime.display_title;
    if (eng && eng.trim() !== '' && eng.toLowerCase() !== 'null') return eng;
    return anime.title || '';
}

/* ════════════════
   AUTH
════════════════ */
async function checkAuth() {
    // Improvement 4: serve cached result within TTL to avoid hammering /api/auth/me
    if (authCache !== null && (Date.now() - authCacheTs) < AUTH_CACHE_TTL) {
        return authCache;
    }
    try {
        const res  = await fetch('/api/auth/me');
        const data = await res.json();
        const profileDiv = document.getElementById('userProfile');

        if (data.status === 'success') {
            authCache = true;
            authCacheTs = Date.now();
            if (profileDiv) profileDiv.innerHTML = `
                <span class="user-email">👤 ${data.user.email}</span>
                <a href="javascript:void(0)" onclick="logout(event)" class="logout-link">🚪 Logout</a>
            `;
            const adminLink = document.getElementById('adminLink');
            if (adminLink && data.user.role === 'admin') adminLink.style.display = 'flex';
            return true;
        } else {
            authCache = false;
            authCacheTs = Date.now();
            // BUG 7: guard against double redirect
            if (!isRedirecting && window.location.pathname !== '/login') {
                isRedirecting = true;
                window.location.replace('/login');
            }
            return false;
        }
    } catch {
        authCache = false;
        authCacheTs = Date.now();
        if (!isRedirecting && window.location.pathname !== '/login') {
            isRedirecting = true;
            window.location.replace('/login');
        }
    }
}

async function checkAuthSilent() {
    try {
        const r = await fetch('/api/auth/me');
        const d = await r.json();
        return d.status === 'success';
    } catch { return false; }
}

async function logout(e) {
    if (e) e.preventDefault();
    const btn = e?.currentTarget;
    if (btn) { btn.innerHTML = '⌛'; btn.style.pointerEvents = 'none'; }
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
        authCache = false;
        window.location.href = '/login';
    } catch { location.reload(); }
}

/* ════════════════
   SAKURA PETALS (Home hero)
════════════════ */
function initSakura() {
    const container = document.getElementById('sakuraContainer');
    if (!container) return;
    container.innerHTML = '';
    const count = 10;

    // Inject per-petal keyframes
    const sheet = document.createElement('style');
    let css = '';
    for (let i = 0; i < count; i++) {
        const drift = -40 + Math.random() * 100;
        css += `
.petal-h${i} {
    animation-name: petalH${i};
}
@keyframes petalH${i} {
    0%   { opacity: 0; transform: translateX(0) translateY(-30px) rotate(0deg); }
    10%  { opacity: 0.8; }
    90%  { opacity: 0.3; }
    100% { opacity: 0; transform: translateX(${drift}px) translateY(560px) rotate(${300 + i * 40}deg); }
}`;
    }
    sheet.textContent = css;
    document.head.appendChild(sheet);

    for (let i = 0; i < count; i++) {
        const p = document.createElement('div');
        p.className = `petal petal-h${i}`;
        p.style.cssText = `
            left: ${Math.random() * 96}%;
            width: ${9 + Math.random() * 9}px;
            height: ${7 + Math.random() * 7}px;
            animation-duration: ${7 + Math.random() * 9}s;
            animation-delay: ${Math.random() * 10}s;
            animation-iteration-count: infinite;
        `;
        container.appendChild(p);
    }
}

/* ════════════════
   HERO BANNER
════════════════ */
// BUG 2: Separate hero fetch from /api/anime/hero — only Ongoing with images
async function fetchHeroAnime() {
    try {
        const res  = await fetch('/api/anime/hero');
        const data = await res.json();
        // Filter out anything still missing a poster just in case
        const heroes = data.filter(a => a.poster_url && a.poster_url.trim());
        if (heroes.length > 0) {
            buildHero(heroes);
        }
    } catch (err) {
        console.warn('Hero fetch failed, hero banner will be skipped.', err);
    }
}

function buildHero(animeList) {
    heroAnimeData = animeList.filter(a => a.poster_url).slice(0, 5);
    if (!heroAnimeData.length) return;

    const banner   = document.getElementById('heroBanner');
    const dotsWrap = document.getElementById('heroDots');
    if (!banner) return;

    // Remove existing slides but keep sakura + dots
    banner.querySelectorAll('.hero-slide').forEach(s => s.remove());
    dotsWrap.innerHTML = '';

    heroAnimeData.forEach((anime, idx) => {
        const genres = (anime.genres || '').split(',').slice(0, 3);
        const slide  = document.createElement('div');
        slide.className = 'hero-slide' + (idx === 0 ? ' active' : '');
        slide.innerHTML = `
            <div class="hero-bg" style="background-image: url('${anime.poster_url}');"></div>
            <div class="hero-overlay"></div>
            <div class="hero-content">
                <div class="hero-text">
                    <div class="hero-genre-tags">
                        ${genres.map(g => `<span class="hero-tag">${g.trim()}</span>`).join('')}
                        <span class="hero-tag status-tag-${anime.status}">${anime.status}</span>
                        ${anime.status === 'Ongoing' && anime.episodes_current ? `<span class="hero-tag ep-tag">EP ${anime.episodes_current}</span>` : ''}
                    </div>
                    <h1 class="hero-title">${getTitle(anime)}</h1>
                    <p class="hero-synopsis">${anime.description ? stripHtml(anime.description).substring(0, 180) + '…' : 'No synopsis available.'}</p>
                    <div class="hero-buttons">
                        <a href="/detail.html?id=${anime.id}" class="btn-hero-primary">▶ Watch Details</a>
                        <button class="btn-hero-secondary" onclick="toggleWatchlistHero(event, ${anime.id})">🔖 Add to List</button>
                    </div>
                </div>
            </div>
        `;
        banner.insertBefore(slide, dotsWrap);

        const dot = document.createElement('div');
        dot.className = 'hero-dot' + (idx === 0 ? ' active' : '');
        dot.onclick = () => setHeroSlide(idx);
        dotsWrap.appendChild(dot);
    });

    startHeroRotation();
}

function setHeroSlide(idx) {
    heroIndex = idx;
    document.querySelectorAll('.hero-slide').forEach((s, i) => s.classList.toggle('active', i === idx));
    document.querySelectorAll('.hero-dot').forEach((d, i) => d.classList.toggle('active', i === idx));
    startHeroRotation(); // Reset the timer when manually clicked
}

function startHeroRotation() {
    if (heroInterval) clearInterval(heroInterval);
    if (heroAnimeData.length < 2) return;
    heroInterval = setInterval(() => {
        heroIndex = (heroIndex + 1) % heroAnimeData.length;
        document.querySelectorAll('.hero-slide').forEach((s, i) => s.classList.toggle('active', i === heroIndex));
        document.querySelectorAll('.hero-dot').forEach((d, i) => d.classList.toggle('active', i === heroIndex));
    }, 6000);
}

async function toggleWatchlistHero(e, animeId) {
    e.preventDefault();
    const btn = e.currentTarget;
    try {
        const res  = await fetch('/api/watchlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ anime_id: animeId })
        });
        const data = await res.json();
        if (data.status === 'success') {
            btn.textContent = '✓ Added';
            btn.style.borderColor = '#4ade80';
            btn.style.color       = '#4ade80';
        } else if (data.message === 'Login required') {
            window.location.href = '/login';
        }
    } catch { console.error('Hero watchlist error'); }
}

/* ════════════════
   FETCH ANIME
════════════════ */
async function fetchAnime(mode = null, append = false, reset = false) {
    const thisFetchId = ++lastFetchId;
    if (mode === '') mode = 'home';
    if (mode) currentMode = mode;

    if (!append) {
        currentPage = 0;

        if (reset || currentMode === 'reset') {
            document.getElementById('searchInput').value = '';
            document.getElementById('statusFilter').value = '';
            document.getElementById('categoryFilter').value = '';
            if (currentMode === 'reset') currentMode = 'home';
        }
    }

    const countryMap = { "Korean": "KR", "Chinese": "CN", "Japanese": "JP" };

    /* Sync category dropdown */
    const catFilter = document.getElementById('categoryFilter');
    if (genreList.includes(currentMode)) catFilter.value = currentMode;
    else if (countryMap[currentMode])       catFilter.value = currentMode;
    else if (['home','trending','watchlist'].includes(currentMode)) catFilter.value = '';

    const search      = document.getElementById('searchInput').value;
    // Feature 3: normalize search — deduplicate tokens before sending
    const normalizedSearch = normalizeSearch(search);
    const status      = document.getElementById('statusFilter').value;
    // BUG 4: apply GENRE_API_MAP so nav labels map to exact AniList genre strings
    const rawCategory = document.getElementById('categoryFilter').value;
    const category    = GENRE_API_MAP[rawCategory] || rawCategory;

    const qp = new URLSearchParams();
    qp.set('limit',  PAGE_SIZE);
    qp.set('offset', currentPage * PAGE_SIZE);
    qp.set('mode',   currentMode);
    if (normalizedSearch) qp.set('search', normalizedSearch);
    if (status)           qp.set('status', status);
    if (category) {
        if (countryMap[category]) qp.set('country', countryMap[category]);
        else qp.set('category', category);
    }

    const url = `/api/anime?${qp.toString()}`;

    /* Update browser history */
    if (!append && arguments[3] !== 'popstate') {
        const stateUrl = `/?${qp.toString()}`;
        if (reset) history.replaceState({ mode: currentMode, search, status, category }, '', stateUrl);
        else        history.pushState({ mode: currentMode, search, status, category }, '', stateUrl);
    }

    /* Update grid title */
    updateMainGridTitle(currentMode);

    /* Improvement 1: skeleton cards while loading */
    if (!append) {
        const grid = document.getElementById('animeGrid');
        if (grid) {
            grid.innerHTML = Array(8).fill(`
                <div class="anime-card" style="pointer-events:none;">
                    <div style="width:100%;height:280px;background:linear-gradient(90deg,#111120 25%,#1a1a2e 50%,#111120 75%);
                         background-size:200% 100%;animation:skelShimmer 1.4s infinite;border-radius:14px 14px 0 0;"></div>
                    <div style="padding:1rem;">
                        <div style="height:12px;width:60%;border-radius:4px;margin-bottom:8px;
                             background:linear-gradient(90deg,#111120 25%,#1a1a2e 50%,#111120 75%);
                             background-size:200% 100%;animation:skelShimmer 1.4s infinite;"></div>
                        <div style="height:10px;width:40%;border-radius:4px;
                             background:linear-gradient(90deg,#111120 25%,#1a1a2e 50%,#111120 75%);
                             background-size:200% 100%;animation:skelShimmer 1.4s infinite;"></div>
                    </div>
                </div>`).join('');
            // inject shimmer keyframe once
            if (!document.getElementById('skelStyle')) {
                const ss = document.createElement('style');
                ss.id = 'skelStyle';
                ss.textContent = '@keyframes skelShimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}';
                document.head.appendChild(ss);
            }
        }
    }

    try {
        const res  = await fetch(url);
        const data = await res.json();
        if (thisFetchId !== lastFetchId) return;

        renderGrid(data, append);
        updateActiveLink(currentMode);

        /* Load hero from first page of home mode */
        if (currentMode === 'home' && !append && !search && !status && !category) {
            showHomeSections(data);
        } else {
            hideHomeSections();
        }

        const btn = document.getElementById('loadMoreBtn');
        if (btn) btn.style.display = data.length < PAGE_SIZE ? 'none' : 'inline-flex';
    } catch (err) {
        // Improvement 5: error boundary — show cached-data banner
        console.error('Fetch error:', err);
        if (!append && thisFetchId === lastFetchId) {
            renderGrid([]);
            let banner = document.getElementById('apiDownBanner');
            if (!banner) {
                banner = document.createElement('div');
                banner.id = 'apiDownBanner';
                banner.style.cssText = 'width:100%;padding:0.6rem 1rem;background:rgba(250,204,21,0.12);'
                    + 'border:1px solid rgba(250,204,21,0.3);border-radius:10px;text-align:center;'
                    + 'color:#facc15;font-size:0.85rem;margin-bottom:1rem;';
                banner.textContent = '⚠️ AniList API is currently unreachable. Showing cached data.';
                const grid = document.getElementById('animeGrid');
                if (grid && grid.parentNode) grid.parentNode.insertBefore(banner, grid);
            }
        }
    }
}

/* ─── Home section toggle ─── */
async function showHomeSections(animeData) {
    // Show hero
    const heroBanner = document.getElementById('heroBanner');
    if (heroBanner) heroBanner.style.display = 'block';

    // Fetch trending for the compact list
    fetchTrendingSection();

    // Ongoing scroll row
    fetchScrollRow('Ongoing',   'ongoingScrollRow',   'ongoingSection');
    // Completed scroll row
    fetchScrollRow('Completed', 'completedScrollRow', 'completedSection');
}

function hideHomeSections() {
    const heroBanner = document.getElementById('heroBanner');
    if (heroBanner) heroBanner.style.display = 'none';

    ['trendingSection','ongoingSection','completedSection'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });

    if (heroInterval) { clearInterval(heroInterval); heroInterval = null; }
}

async function fetchTrendingSection() {
    const section = document.getElementById('trendingSection');
    const list    = document.getElementById('trendingList');
    if (!section || !list) return;

    try {
        const res  = await fetch('/api/anime?mode=trending&limit=10&offset=0');
        const data = await res.json();
        if (!data.length) return;
        section.style.display = 'block';
        section.style.animation = 'fadeIn 0.5s ease';

        list.innerHTML = data.map((a, i) => `
            <a href="/detail.html?id=${a.id}" class="trending-item">
                <span class="trending-rank">${i + 1}</span>
                <img src="${a.poster_url}" alt="${getTitle(a)}" class="trending-thumb" onerror="this.src='https://via.placeholder.com/48x68/111120/ff2d6b?text=?'">
                <div class="trending-info">
                    <div class="trending-title">${getTitle(a)}</div>
                    <div class="trending-meta">
                        ${a.genres ? a.genres.split(',').slice(0,2).map(g => `<span class="trending-genre">${g.trim()}</span>`).join('') : ''}
                        ${a.rating_score ? `<span class="trending-score">⭐ ${a.rating_score.toFixed(1)}</span>` : ''}
                        <span class="status-badge status-${a.status}">${a.status}</span>
                    </div>
                </div>
                <span class="trending-arrow">↑</span>
            </a>
        `).join('');
    } catch { console.error('Trending section error'); }
}

async function fetchScrollRow(statusVal, rowId, sectionId) {
    const section = document.getElementById(sectionId);
    const row     = document.getElementById(rowId);
    if (!section || !row) return;

    try {
        const res  = await fetch(`/api/anime?mode=home&status=${statusVal}&limit=20&offset=0`);
        const data = await res.json();
        if (!data.length) return;

        section.style.display = 'block';
        section.style.animation = 'fadeIn 0.5s ease';

        row.innerHTML = data.map(a => {
            const rating = a.rating_score;
            const rClass = !rating ? 'none' : rating >= 8 ? 'high' : rating >= 6 ? 'mid' : 'low';
            const rLabel = rating ? rating.toFixed(1) : 'N/A';
            const displayTitle = getTitle(a);
            const epInfo = a.status === 'Ongoing' ? `EP ${a.episodes_current || '?'}` : (a.episodes_total ? `${a.episodes_total} EP` : '');
            return `
            <div class="anime-card-poster" onclick="location.href='/detail.html?id=${a.id}'">
                <img src="${a.poster_url}" alt="${displayTitle}" loading="lazy" onerror="this.src='https://via.placeholder.com/155x230/111120/ff2d6b?text=No+Poster'">
                <span class="status-badge status-${a.status}">${a.status}</span>
                ${epInfo ? `<span class="ep-badge-overlay">${epInfo}</span>` : ''}
                <span class="rating-badge ${rClass}">⭐ ${rLabel}</span>
                <div class="poster-overlay">
                    <div class="overlay-title">${displayTitle}</div>
                    <div class="overlay-meta">
                        <span class="overlay-rating">⭐ ${rLabel}</span>
                        <button class="overlay-add-btn" onclick="event.stopPropagation(); toggleWatchlistCard(event, ${a.id}, this)" title="Add to List">+</button>
                    </div>
                </div>
            </div>`;
        }).join('');
    } catch { console.error(`${sectionId} scroll row error`); }
}

function filterByStatus(statusVal) {
    document.getElementById('statusFilter').value = statusVal;
    fetchAnime('home');
}

/* ─── Grid title ─── */
const titleMap = {
    home:       '🌸 All Anime',
    trending:   '🔥 Trending Now',
    watchlist:  '🔖 My Watchlist',
    upcoming:   '📅 Upcoming Releases',
    'Action & Adventure':    '⚔️ Action & Adventure',
    'Romance':               '💖 Romance',
    'Fantasy':               '🪄 Fantasy',
    'Supernatural & Horror': '👻 Horror',   // Improvement 3
    'Horror':                '👻 Horror',   // alias for nav tab label
    'Isekai':                '🌀 Isekai',
    'Slice of Life':         '🌿 Slice of Life',
    'Dark Fantasy':          '🌑 Dark Fantasy',
    'Sci-Fi & Mecha':        '🤖 Sci-Fi & Mecha',
    'Sports':                '🏆 Sports',
    'Mahou Shoujo':          '✨ Mahou Shoujo',
};

function updateMainGridTitle(mode) {
    const el = document.getElementById('mainGridTitle');
    if (el) el.textContent = titleMap[mode] || '🌸 All Anime';
}

/* ─── Active Nav Link ─── */
function updateActiveLink(mode) {
    document.querySelectorAll('.sidebar nav a').forEach(a => {
        a.classList.toggle('active', a.getAttribute('data-mode') === mode);
    });
}

/* ════════════════
   RENDER GRID
════════════════ */
async function renderGrid(animeList, append = false) {
    const grid = document.getElementById('animeGrid');
    if (!append) grid.innerHTML = '';

    const loader = grid.querySelector('.loading');
    if (loader) loader.remove();

    if (!append && animeList.length === 0) {
        grid.innerHTML = currentMode === 'watchlist' ? `
            <div class="no-results">
                <div class="no-results-icon">🔖</div>
                <h3>Your List is Empty</h3>
                <p>You haven't added any anime to your list yet. Browse the home page and click the + icon to save your favorites!</p>
                <button onclick="fetchAnime('home',false,true)">Browse Anime</button>
            </div>` : `
            <div class="no-results">
                <div class="no-results-icon">🔍</div>
                <h3>No results found.</h3>
                <p>We couldn't find any anime matching your criteria. Try adjusting your filters.</p>
            </div>`;
        return;
    }

    animeList.forEach((anime, idx) => {
        const card = document.createElement('div');
        card.className = 'anime-card';
        card.style.animationDelay = `${idx * 40}ms`;

        const genres = anime.genres ? anime.genres.split(',').slice(0, 2) : [];
        const genreHtml = genres.map(g => `<span class="genre-tag">${g.trim()}</span>`).join('');

        const rating = anime.rating_score;
        let ratingHtml = '';
        if (rating) {
            ratingHtml = `<span class="grid-rating">⭐ ${rating.toFixed(1)}</span>`;
        } else if (anime.status === 'Upcoming') {
            const rd = anime.release_date && anime.release_date !== 'TBA' ? new Date(anime.release_date) : null;
            ratingHtml = (rd && rd <= new Date())
                ? `<span class="grid-rating">Rating N/A</span>`
                : `<span class="status-upcoming-text">Upcoming</span>`;
        } else {
            ratingHtml = `<span class="grid-rating" style="color:var(--text-muted);">N/A</span>`;
        }

        let epInfo = '';
        if (anime.status === 'Ongoing')   epInfo = `EP ${anime.episodes_current || 0} / ${anime.episodes_total || '?'}`;
        if (anime.status === 'Completed') epInfo = `${anime.episodes_total || '?'} Episodes`;

        const lastEpName = anime.last_episode_name ? `<p class="last-ep">Latest: ${anime.last_episode_name}</p>` : '';

        const descText = anime.description
            ? stripHtml(anime.description).substring(0, 80) + '…'
            : 'No description available.';

        card.innerHTML = `
            <a href="/detail.html?id=${anime.id}" class="card-link">
                <div class="card-inner">
                    <span class="status-badge status-${anime.status}">${anime.status}</span>
                    <img src="${anime.poster_url}" alt="${getTitle(anime)}" class="poster" loading="lazy"
                         onerror="this.src='https://via.placeholder.com/200x280/111120/ff2d6b?text=No+Poster'">
                    <div class="card-content">
                        <div class="meta-top">
                            ${ratingHtml}
                            <span class="release-date">📅 ${anime.release_date || 'TBA'}</span>
                        </div>
                        <h3>${getTitle(anime)}</h3>
                        ${epInfo ? `<div class="ep-badge">${epInfo}</div>` : ''}
                        ${lastEpName}
                        <div class="genre-list">${genreHtml}</div>
                        <div class="description"><div class="description-text">${descText}</div></div>
                    </div>
                </div>
            </a>
            <button class="watchlist-btn" id="watchlist-btn-${anime.id}"
                    onclick="toggleWatchlist(event, ${anime.id})"
                    title="${currentMode === 'watchlist' ? 'Remove from List' : 'Add to My List'}">
                ${currentMode === 'watchlist' ? '➖' : '➕'}
            </button>
        `;
        grid.appendChild(card);
    });
}

/* ─── Strip HTML from descriptions ─── */
function stripHtml(html) {
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    return tmp.textContent || tmp.innerText || '';
}

/* ════════════════
   WATCHLIST
════════════════ */
async function toggleWatchlist(e, animeId) {
    if (e) { e.stopPropagation(); e.preventDefault(); }
    const btn     = document.getElementById(`watchlist-btn-${animeId}`);
    const isRemove = btn.textContent.trim() === '➖';

    try {
        const res  = await fetch('/api/watchlist', {
            method: isRemove ? 'DELETE' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ anime_id: animeId })
        });
        const data = await res.json();
        if (data.status === 'success') {
            // Improvement 2: toast feedback
            showToast(isRemove ? '🗑️ Removed from My List' : '🔖 Added to My List!');
            if (currentMode === 'watchlist') fetchAnime('watchlist');
            else {
                btn.textContent = isRemove ? '➕' : '➖';
                btn.title = isRemove ? 'Add to My List' : 'Remove from List';
            }
        } else if (data.message === 'Login required') {
            window.location.href = '/login';
        }
    } catch { console.error('Watchlist error'); }
}

async function toggleWatchlistCard(e, animeId, btn) {
    e.stopPropagation();
    try {
        const res  = await fetch('/api/watchlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ anime_id: animeId })
        });
        const data = await res.json();
        if (data.status === 'success') {
            btn.textContent = '✓';
            btn.style.background = 'linear-gradient(135deg, #22c55e, #16a34a)';
            showToast('🔖 Added to My List!');
        } else if (data.message === 'Login required') {
            window.location.href = '/login';
        }
    } catch {}
}

/* ════════════════
   LOAD MORE
════════════════ */
function loadMore() {
    currentPage++;
    fetchAnime(currentMode, true);
}

/* ════════════════
   HEADER SCROLL EFFECT
════════════════ */
const mainHeader = document.getElementById('mainHeader');
if (mainHeader) {
    window.addEventListener('scroll', () => {
        mainHeader.classList.toggle('scrolled', window.scrollY > 40);
    }, { passive: true });
}

/* ════════════════
   SEARCH + FILTERS
════════════════ */
const searchInput    = document.getElementById('searchInput');
const clearSearchBtn = document.getElementById('clearSearchBtn');  // legacy alias
const searchClear    = document.getElementById('searchClear');     // Feature 2

// Feature 3: normalize search query (deduplicate tokens)
function normalizeSearch(q) {
    if (!q) return '';
    const words  = q.trim().toLowerCase().split(/\s+/);
    const unique = [...new Set(words)].filter(w => w.length >= 2);
    return unique.join(' ');
}

// BUG 2: class-based show/hide (CSS controls default hidden state via #searchClear { display:none })
if (searchClear) {
    searchClear.classList.remove('visible');          // ensure hidden on load

    if (searchInput) {
        searchInput.addEventListener('input', () => {
            searchClear.classList.toggle('visible', searchInput.value.length > 0);
        });
    }

    searchClear.addEventListener('click', () => {
        if (searchInput) {
            searchInput.value = '';
            searchInput.dispatchEvent(new Event('input')); // triggers debounced search
            searchInput.focus();
        }
        searchClear.classList.remove('visible');
        fetchAnime(currentMode, false, false);
    });
}

// Legacy clearSearchBtn handler (index.html may still use old ID)
if (clearSearchBtn) {
    clearSearchBtn.addEventListener('click', () => {
        if (searchInput) searchInput.value = '';
        fetchAnime(currentMode);
    });
}

if (searchInput && !searchClear) {
    // Only attach if Feature 2 searchClear is not present
    const debouncedSearch = debounce(() => fetchAnime(currentMode), 350);
    searchInput.addEventListener('input', debouncedSearch);
} else if (searchInput) {
    const debouncedSearch = debounce(() => fetchAnime(currentMode), 350);
    searchInput.addEventListener('input', debouncedSearch);
}

const statusFilter   = document.getElementById('statusFilter');
const categoryFilter = document.getElementById('categoryFilter');

// BUG 5: debounced handler for filters that could fire duplicate calls
const debouncedFetch = debounce((mode) => fetchAnime(mode), 150);

if (statusFilter)   statusFilter.addEventListener('change', () => debouncedFetch());
if (categoryFilter) categoryFilter.addEventListener('change', (e) => {
    const val = e.target.value;
    debouncedFetch(val === '' ? 'home' : val);
});

/* ════════════════
   POP STATE
════════════════ */
window.onpopstate = (e) => {
    if (e.state) {
        const { mode, search, status, category } = e.state;
        if (searchInput)   searchInput.value   = search   || '';
        if (statusFilter)  statusFilter.value  = status   || '';
        if (categoryFilter) categoryFilter.value = category || '';
        fetchAnime(mode, false, false, 'popstate');
    } else {
        fetchAnime('home', false, true, 'popstate');
    }
};

/* ════════════════
   PERMISSIONS MODAL
════════════════ */
async function checkFirstLogin() {
    if (localStorage.getItem('permissions_configured') === 'true') return;
    if (localStorage.getItem('first_login') === 'true') {
        localStorage.removeItem('first_login');
        const calBtn = document.getElementById('calPermBtn');
        if (localStorage.getItem('calendar_enabled') === 'true' && calBtn) {
            calBtn.textContent = 'Enabled ✓';
            calBtn.classList.add('allowed');
            calBtn.onclick = null;
        }
        const modal = document.getElementById('permissionModal');
        if (modal) modal.style.display = 'flex';
    }
}

function requestCalendarPermission() {
    const btn = document.getElementById('calPermBtn');
    btn.textContent = 'Enabled ✓';
    btn.classList.add('allowed');
    btn.onclick = null;
    localStorage.setItem('calendar_enabled', 'true');
}

function closePermissions() {
    localStorage.setItem('permissions_configured', 'true');
    const modal = document.getElementById('permissionModal');
    if (modal) modal.style.display = 'none';
}

/* ════════════════
   SERVICE WORKER / PUSH
════════════════ */
async function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    try {
        const reg = await navigator.serviceWorker.register('/sw.js');
        const banner = document.getElementById('notifyBanner');
        const perm   = await Notification.requestPermission();
        if (perm === 'granted') {
            if (banner) banner.style.display = 'none';
            subscribeUser(reg);
        } else if (perm === 'default' && banner) {
            banner.style.display = 'block';
            banner.onclick = () => registerServiceWorker();
        }
    } catch {}
}

async function subscribeUser(reg) {
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
        const res = await fetch('/api/vapid-public-key');
        const { publicKey } = await res.json();
        sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(publicKey) });
        await fetch('/api/subscribe', { method: 'POST', body: JSON.stringify(sub), headers: { 'Content-Type': 'application/json' } });
    }
}

function urlBase64ToUint8Array(b64) {
    const padding = '='.repeat((4 - b64.length % 4) % 4);
    const b = (b64 + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = window.atob(b);
    return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

/* ════════════════
   REVIEW (legacy support)
════════════════ */
async function fetchReviews(animeId) {
    const list = document.querySelector(`#reviews-${animeId} .reviews-list`);
    if (!list) return;
    try {
        const res     = await fetch(`/api/reviews/${animeId}`);
        const reviews = await res.json();
        list.innerHTML = reviews.length === 0
            ? '<p style="font-size:0.8rem;margin:1rem 0;">No reviews yet.</p>'
            : reviews.map(r => `
            <div class="review-item">
                <div class="review-header">
                    <strong>${r.username}</strong>
                    <span class="rating-stars">${'⭐'.repeat(r.rating)}</span>
                </div>
                <p class="review-comment">${r.comment}</p>
            </div>`).join('');
    } catch { if (list) list.innerHTML = 'Error loading reviews.'; }
}

async function submitReview(e, animeId) {
    e.preventDefault();
    const form = e.target;
    const data = { anime_id: animeId, rating: parseInt(form.querySelector('.rev-rating').value), comment: form.querySelector('.rev-comment').value };
    try {
        const res    = await fetch('/api/reviews', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        const result = await res.json();
        if (result.status === 'success') { form.reset(); fetchReviews(animeId); }
        else alert(result.message || 'Failed to post review.');
    } catch { alert('Failed to post review.'); }
}

/* ════════════════
   LAST UPDATED (Feature 1)
════════════════ */
function timeAgo(isoStr) {
    if (!isoStr) return null;
    const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
    if (diff < 60)          return 'just now';
    if (diff < 3600)        return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400)       return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

async function pollLastUpdate() {
    try {
        const res  = await fetch('/api/last-update');
        const data = await res.json();
        const el   = document.getElementById('lastUpdatedBanner');
        if (el && data.last_update) {
            el.textContent = `Updated: ${timeAgo(data.last_update)}`;
            el.style.display = 'block';
        }
    } catch {}
}

/* ════════════════
   INIT
════════════════ */
(async function init() {
    await checkAuth();
    initSakura();
    fetchAnime('home', false, true);
    fetchHeroAnime();          // BUG 2: hero fetched separately
    registerServiceWorker();
    checkFirstLogin();
    pollLastUpdate();          // Feature 1: show last update time
    setInterval(pollLastUpdate, 60_000);
})();
