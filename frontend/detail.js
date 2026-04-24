let currentAnime = null;

/* FEATURE 1: Always prefer English title when available */
function getTitle(anime) {
    if (!anime) return '';
    const eng = anime.title_english || anime.display_title;
    if (eng && eng.trim() !== '' && eng.toLowerCase() !== 'null') return eng;
    return anime.title || '';
}

async function fetchDetail() {
    const urlParams = new URLSearchParams(window.location.search);
    const animeId = urlParams.get('id');

    if (!animeId) {
        window.location.href = '/';
        return;
    }

    try {
        const response = await fetch(`/api/anime/${animeId}`);
        const anime = await response.json();

        if (anime.status === 'error') {
            document.getElementById('detailContainer').innerHTML = `<h3>${anime.message}</h3>`;
            return;
        }

        currentAnime = anime;
        document.title = `AniNews | ${getTitle(anime)}`;
        renderDetail(anime);

        // Fire all secondary requests simultaneously — no sequential waterfall
        await Promise.all([
            fetchRelated(animeId),
            checkWatchlist(animeId),
            anime.status !== 'Upcoming' ? fetchReviews(anime.id) : Promise.resolve()
        ]);
    } catch (error) {
        console.error('Error fetching anime details:', error);
    }
}

function renderDetail(anime) {
    const container = document.getElementById('detailContainer');

    // Ratings Star UI — Unicode ★ with gold/dim colours
    const score = anime.rating_score || 0;
    const filledCount = Math.round(score / 2);
    const stars = '<span style="color:#ffd700;font-size:18px;">'
        + '★'.repeat(filledCount)
        + '</span><span style="color:rgba(255,255,255,0.2);font-size:18px;">'
        + '☆'.repeat(5 - filledCount)
        + '</span>';

    let ratingDisplay = '';
    if (anime.rating_score) {
        ratingDisplay = `${score.toFixed(1)} / 10 (${anime.rating_votes || 0} votes)`;
    } else if (anime.status === 'Upcoming') {
        const releaseDate = anime.release_date && anime.release_date !== 'TBA' ? new Date(anime.release_date) : null;
        const today = new Date();
        if (releaseDate && releaseDate <= today) {
            ratingDisplay = 'Rating not available';
        } else {
            ratingDisplay = 'Upcoming';
        }
    } else {
        ratingDisplay = 'Rating not available';
    }

    // Categories / Genres from relational list
    const genres = anime.genres_list || (anime.genres ? anime.genres.split(',') : []);
    const genreHtml = genres.map(g => `<span class="meta-item">${g}</span>`).join('');

    // Countdown Logic
    let countdownHtml = '';
    if (anime.status === 'Ongoing' && anime.next_episode_date) {
        countdownHtml = `
            <div class="countdown-box">
                <p>Next Episode (${(anime.episodes_current || 0) + 1}) in:</p>
                <div id="countdown" class="countdown-timer">Calculating...</div>
            </div>
        `;
        startCountdown(anime.next_episode_date);
    }

    // Episodes List — BUG 3: hianime-style compact number grid
    let episodeHtml = '';
    const episodes = anime.episodes_list || [];
    const EP_PAGE_SIZE = 100;

    // Build synthetic list if no detailed episode list available
    // Determine the max number of episodes to generate if episodes_list is empty
    const maxEps = Math.max(anime.episodes_total || 0, anime.episodes_current || anime.last_episode_number || 0);
    
    let allEps = episodes.length > 0
        ? episodes
        : (anime.status === 'Completed' || anime.status === 'Ongoing') && maxEps > 0
            ? Array.from({ length: maxEps }, (_, i) => ({ episode_number: i + 1 }))
            : [];

    if (allEps.length > 0) {
        // Store globally for re-render on page/jump change
        window._allEpisodes = allEps;
        window._currentEp   = 1;
        window._epPageSize  = EP_PAGE_SIZE;

        episodeHtml = `
            <div class="episodes-section">
                <div class="sec-header">
                    <h3 class="sec-title">Episode List</h3>
                    <span class="ep-count">${allEps.length} episodes</span>
                </div>
                <div id="episodeSection">${buildEpGrid(allEps, 0, 1, EP_PAGE_SIZE)}</div>
            </div>
        `;
    }

    // Comments Section (Only for released anime)
    let reviewsHtml = '';
    if (anime.status !== 'Upcoming') {
        reviewsHtml = `
            <div class="reviews-section">
                <h3>Comments</h3>
                <div class="comment-box-wrap">
                    <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.75rem;">
                        <span style="color:var(--text-muted);font-size:0.85rem;">Rating:</span>
                        <select id="ratingInput" style="padding:0.4rem 0.6rem;border-radius:6px;background:rgba(255,255,255,0.08);color:white;border:1px solid rgba(255,255,255,0.15);">
                            <option value="5">&#11088;&#11088;&#11088;&#11088;&#11088; Excellent</option>
                            <option value="4">&#11088;&#11088;&#11088;&#11088; Good</option>
                            <option value="3">&#11088;&#11088;&#11088; Average</option>
                            <option value="2">&#11088;&#11088; Poor</option>
                            <option value="1">&#11088; Terrible</option>
                        </select>
                    </div>
                    <textarea id="commentInput" class="comment-input" placeholder="Share your thoughts..."></textarea>
                    <button class="comment-btn" onclick="submitComment()">Post Comment</button>
                </div>
                <div class="comments-list" id="reviewsList">
                    <div class="no-comments">No comments yet. Be the first!</div>
                </div>
            </div>
        `;
    } else {
        reviewsHtml = `
            <div class="reviews-section" style="opacity:0.6;">
                <h3>Comments</h3>
                <p>Comments will be enabled once the first episode is released.</p>
            </div>
        `;
    }

    // Streaming Platforms — clean pill badges, no emoji
    let streamingHtml = '';
    const platforms = anime.streaming_platforms || [];
    if (platforms.length > 0) {
        streamingHtml = `
            <div class="streaming-section">
                <h3>Where to Watch</h3>
                <div class="streaming-links" style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 1rem;">
                    ${platforms.map(p => `
                        <a href="${p.url}" target="_blank" class="streaming-pill">
                            ${p.platform_name}
                        </a>
                    `).join('')}
                </div>
            </div>
        `;
    } else {
        streamingHtml = `
            <div class="streaming-section">
                <h3>Where to Watch</h3>
                <p style="color: var(--text-dim); margin-top: 1rem;">Streaming platform not available.</p>
            </div>
        `;
    }

    // Hero cover image with fallback gradient
    const coverImgHtml = anime.poster_url
        ? `<img src="${anime.poster_url}" alt="${getTitle(anime)}"
               style="width:200px;height:280px;object-fit:cover;border-radius:12px;
                      box-shadow:0 8px 32px rgba(0,0,0,0.6);flex-shrink:0;">`
        : `<div style="width:200px;height:280px;border-radius:12px;flex-shrink:0;
                       background:linear-gradient(135deg,#1a1a2e,#2d1b4e);
                       display:flex;align-items:center;justify-content:center;
                       text-align:center;padding:1rem;font-weight:700;
                       color:rgba(255,255,255,0.6);font-size:0.9rem;">${getTitle(anime)}</div>`;

    const reminderBtnHtml = anime.status === 'Completed' ? '' : `
        <button class="detail-remind-btn" onclick="openReminderModal()">🔔 Remind Me</button>`;

    container.innerHTML = `
        <div class="detail-hero" style="display:flex;gap:2rem;align-items:flex-start;flex-wrap:wrap;margin-bottom:2rem;">
            ${coverImgHtml}
            <div style="flex:1;min-width:220px;">
                <span class="status-badge status-${anime.status}" style="margin-bottom:0.75rem;display:inline-block;">${anime.status}</span>
                <h1 style="font-size:2rem;margin-bottom:1rem;line-height:1.2;">${getTitle(anime)}</h1>
                <div class="meta-row" style="flex-direction:column;gap:0.5rem;align-items:flex-start;margin-bottom:1rem;">
                    <span class="meta-item">🏢 ${anime.studio || 'Unknown'}</span>
                    <span class="meta-item">🎬 ${anime.episodes_total || 'TBA'} Episodes</span>
                    <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">${genreHtml}</div>
                </div>

                <div class="rating-box" style="margin:1.5rem 0;display:flex;align-items:center;gap:1rem;">
                    <div class="rating-score">${score ? score.toFixed(1) : '—'}</div>
                    <div>
                        <div>${stars}</div>
                        <p style="color:var(--text-muted);font-size:0.8rem;margin-top:0.25rem;">${ratingDisplay}</p>
                    </div>
                </div>

                ${countdownHtml}

                <div style="display:flex;flex-direction:column;gap:0.75rem;margin-top:1rem;">
                    ${reminderBtnHtml}
                    <button id="watchlistDetailBtn" class="detail-watchlist-btn" onclick="toggleWatchlistDetail(${anime.id})">
                        🔖 Add to My List
                    </button>
                </div>
            </div>
        </div>

        <div class="detail-info">
            ${streamingHtml}

            <div style="margin-top:3rem;">
                <div class="description">
                    <h3>Synopsis</h3>
                    <p style="line-height:1.8;margin-top:1.2rem;">${anime.description || 'No synopsis available.'}</p>
                </div>
            </div>

            <div style="margin-top:3rem;">
                ${episodeHtml}
            </div>

            <div style="margin-top:3rem;">
                ${reviewsHtml}
            </div>
        </div>
    `;

    // NOTE: fetchReviews is called via Promise.all in fetchDetail()
}

function startCountdown(dateStr) {
    const target = new Date(dateStr).getTime();

    const x = setInterval(function () {
        const now = new Date().getTime();
        const distance = target - now;

        const days = Math.floor(distance / (1000 * 60 * 60 * 24));
        const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
        const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
        const seconds = Math.floor((distance % (1000 * 60)) / 1000);

        const countdownEl = document.getElementById("countdown");
        if (countdownEl) {
            countdownEl.innerHTML = days + "d " + hours + "h " + minutes + "m " + seconds + "s ";
        }

        if (distance < 0) {
            clearInterval(x);
            if (countdownEl) countdownEl.innerHTML = "RELEASED";
        }
    }, 1000);
}

async function fetchReviews(animeId) {
    const list = document.getElementById('reviewsList');
    if (!list) return;

    try {
        const response = await fetch(`/api/reviews/${animeId}`);
        const reviews = await response.json();

        if (reviews.length === 0) {
            list.innerHTML = '<p>No comments yet. Be the first to share your thoughts!</p>';
            return;
        }

        list.innerHTML = reviews.map(r => `
            <div class="review-item" style="border-bottom: 1px solid var(--glass-border); padding: 1rem 0;">
                <div class="review-header">
                    <strong>${r.username}</strong> 
                    <span style="color: #facc15; margin-left: 1rem;">${'⭐'.repeat(r.rating)}</span>
                    <small style="color: var(--text-dim); margin-left: 1rem;">${new Date(r.created_at).toLocaleDateString()}</small>
                </div>
                <p style="margin-top: 0.5rem; line-height: 1.5;">${r.comment}</p>
            </div>
        `).join('');
    } catch (error) {
        list.innerHTML = '<p style="color: var(--text-dim);">Comment is not available</p>';
    }
}

async function fetchRelated(animeId) {
    try {
        const response = await fetch(`/api/anime/${animeId}/related`);
        const related  = await response.json();

        const container = document.querySelector('.containerRelated');
        if (!container) return;

        const section = document.createElement('div');
        section.className = 'related-section';

        if (!related || related.length === 0) {
            section.innerHTML = '<h3 style="margin-top:3rem;">Related Anime</h3><p style="color:rgba(255,255,255,0.3);margin-top:1rem;">No related anime found.</p>';
            container.appendChild(section);
            return;
        }

        // FEATURE 3: Horizontal-scroll card row
        section.innerHTML = `
            <div class="rel-header">
                <h3 class="rel-title">You Might Also Like</h3>
                <span class="rel-sub">Based on genres</span>
            </div>
            <div class="rel-scroll">
                ${related.map(a => {
                    const title = getTitle(a);
                    const img   = a.cover_image || a.poster_url || '';
                    const score = a.rating_score ? parseFloat(a.rating_score).toFixed(1) : null;
                    const statusLow = (a.status || '').toLowerCase();
                    let firstGenre = '';
                    try { firstGenre = JSON.parse(a.genres || '[]')[0] || ''; } catch { firstGenre = (a.genres || '').split(',')[0]?.trim() || ''; }
                    return `
                    <a href="/detail.html?id=${a.id}" class="rel-card">
                        <div class="rel-poster">
                            ${img
                                ? `<img src="${img}" alt="${title}" loading="lazy" onerror="this.style.display='none'">`
                                : `<div class="rel-noimg">${title.substring(0,2)}</div>`
                            }
                            ${a.status === 'Ongoing' && a.episodes_current ? `<span class="ep-badge-overlay" style="bottom:4px;left:4px;font-size:0.6rem;">EP ${a.episodes_current}</span>` : (a.episodes_total ? `<span class="ep-badge-overlay" style="bottom:4px;left:4px;font-size:0.6rem;">${a.episodes_total} EP</span>` : '')}
                            ${score ? `<div class="rel-score">&#9733; ${score}</div>` : ''}
                            ${a.status ? `<div class="rel-status rel-${statusLow}">${a.status}</div>` : ''}
                        </div>
                        <div class="rel-name">${title}</div>
                        ${firstGenre ? `<div class="rel-genre">${firstGenre}</div>` : ''}
                    </a>`;
                }).join('')}
            </div>
        `;
        container.appendChild(section);
    } catch (err) {
        console.error('fetchRelated error', err);
    }
}

async function submitComment() {
    const comment = document.getElementById('commentInput').value;
    if (!comment.trim()) return alert("Comment is empty.");

    const rating = document.getElementById('ratingInput').value;
    try {
        const response = await fetch('/api/reviews', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ anime_id: currentAnime.id, rating: parseInt(rating), comment })
        });
        const data = await response.json();
        if (data.status === 'success') {
            document.getElementById('commentInput').value = '';
            fetchReviews(currentAnime.id);
        } else {
            alert(data.message);
        }
    } catch (e) {
        alert("Login required to comment.");
    }
}

// Reminder Buttons simplified logic is already present in detail.js as reminderOptionA (Calendar) and reminderOptionB (Gmail). 
// The modal in detail.html was updated in previous steps to only show these two.
function openReminderModal() {
    document.getElementById('reminderModal').classList.add('open');
    document.body.style.overflow = 'hidden';
    // BUG 1 Fix 3: populate next episode date, default to TBA
    const el = document.getElementById('nextEpTime');
    if (el && currentAnime) {
        const dateStr = currentAnime.next_episode_date || currentAnime.release_date;
        if (dateStr && dateStr !== 'TBA' && dateStr !== 'null') {
            const d = new Date(dateStr);
            el.textContent = isNaN(d.getTime())
                ? dateStr
                : d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
        } else {
            el.textContent = 'TBA';
        }
    } else if (el) {
        el.textContent = 'TBA';
    }
}

function closeReminderModal() {
    document.getElementById('reminderModal').classList.remove('open');
    document.body.style.overflow = '';
}

async function reminderOptionA() {
    if (localStorage.getItem('calendar_enabled') === 'true') {
        const protocol = window.location.protocol === 'https:' ? 'webcals:' : 'webcal:';
        const calendarUrl = `${protocol}//${window.location.host}/api/calendar/${currentAnime.id}.ics`;

        // This browser-level protocol redirect opens the native System Calendar 
        // directly (Safari, Chrome, etc. all support this for direct marking).
        window.location.href = calendarUrl;
    } else {
        const title = getTitle(currentAnime);
        const date = currentAnime.next_episode_date || currentAnime.release_date;
        const start = new Date(date);
        const end = new Date(start.getTime() + 30 * 60 * 1000);
        const formatDate = (d) => d.toISOString().replace(/-|:|\.\d+/g, "");
        const googleUrl = `https://www.google.com/calendar/render?action=TEMPLATE&text=${encodeURIComponent(title)}&dates=${formatDate(start)}/${formatDate(end)}`;
        window.open(googleUrl, '_blank');
    }
    closeReminderModal();
}

async function reminderOptionB() {
    try {
        const response = await fetch('/api/reminders/gmail', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ anime_id: currentAnime.id })
        });
        const data = await response.json();
        alert(data.status === 'success' ? `Success! A reminder will be sent to your registered email.` : data.message);
    } catch (e) {
        alert("Error connecting to server. Please ensure you are logged in.");
    }
    closeReminderModal();
}

window.onclick = function (event) {
    const modal = document.getElementById('reminderModal');
    if (event.target === modal) closeReminderModal();
}

async function checkWatchlist(animeId) {
    try {
        const response = await fetch(`/api/watchlist/check/${animeId}`);
        const data = await response.json();
        const btn = document.getElementById('watchlistDetailBtn');
        if (btn && data.in_watchlist) {
            btn.innerHTML = '✓ In My List';
            btn.setAttribute('data-in-list', 'true');
        }
    } catch (err) { }
}

async function toggleWatchlistDetail(animeId) {
    const btn = document.getElementById('watchlistDetailBtn');
    const isRemove = btn.getAttribute('data-in-list') === 'true';

    try {
        const response = await fetch('/api/watchlist', {
            method: isRemove ? 'DELETE' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ anime_id: animeId })
        });
        const data = await response.json();
        if (data.status === 'success') {
            if (isRemove) {
                btn.innerHTML = '🔖 Add to My List';
                btn.removeAttribute('data-in-list');
            } else {
                btn.innerHTML = '✓ In My List';
                btn.setAttribute('data-in-list', 'true');
            }
        }
    } catch (err) { }
}

async function checkAuth() {
    try {
        const response = await fetch('/api/auth/me');
        const data = await response.json();
        const profileDiv = document.getElementById('userProfile');

        if (data.status === 'success') {
            profileDiv.innerHTML = `
                <span class="user-email">👤 ${data.user.email}</span>
                <a href="javascript:void(0)" onclick="logout(event)" class="logout-link">🚪 Logout</a>
            `;
            const adminLink = document.getElementById('adminLink');
            if (adminLink && data.user.role === 'admin') adminLink.style.display = 'flex';
            return true;
        } else {
            if (window.location.pathname !== '/login') {
                window.location.replace('/login');
            }
            return false;
        }
    } catch (err) {
        console.error('Auth check failed');
        if (window.location.pathname !== '/login') {
            window.location.replace('/login');
        }
    }
}

async function logout(event) {
    if (event) event.preventDefault();
    const btn = event ? event.currentTarget : null;
    if (btn) {
        btn.innerHTML = '⌛ Logging out...';
        btn.style.pointerEvents = 'none';
        btn.style.opacity = '0.7';
    }

    try {
        await fetch('/api/auth/logout', { method: 'POST' });
        window.location.href = '/login';
    } catch (err) {
        console.error('Logout failed', err);
        window.location.href = '/login';
    }
}

/* ─── BUG 3: Hianime-style episode grid helpers ─── */
function buildEpGrid(allEps, pageIndex, activeEp, pageSize) {
    pageSize = pageSize || 100;
    const totalPages = Math.ceil(allEps.length / pageSize);

    const pageOptions = Array.from({ length: totalPages }, (_, i) => {
        const start = i * pageSize + 1;
        const end   = Math.min((i + 1) * pageSize, allEps.length);
        return `<option value="${i}" ${i === pageIndex ? 'selected' : ''}>
            ${String(start).padStart(3,'0')} - ${String(end).padStart(3,'0')}
        </option>`;
    }).join('');

    const pageEps = allEps.slice(pageIndex * pageSize, (pageIndex + 1) * pageSize);

    const cells = pageEps.map(ep => {
        const num = ep.episode_number !== undefined ? ep.episode_number : ep.number;
        const isActive = num === activeEp;
        return `<button class="ep-cell${isActive ? ' ep-active' : ''}"
            onclick="selectEpisode(${num})" title="Episode ${num}">${num}</button>`;
    }).join('');

    return `
        <div class="ep-list-wrap">
            <div class="ep-list-header">
                <div class="ep-range-wrap">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>
                        <line x1="8" y1="18" x2="21" y2="18"/>
                        <circle cx="3" cy="6" r="1.5" fill="currentColor"/>
                        <circle cx="3" cy="12" r="1.5" fill="currentColor"/>
                        <circle cx="3" cy="18" r="1.5" fill="currentColor"/>
                    </svg>
                    <select class="ep-range-select" onchange="changeEpPage(this.value)">${pageOptions}</select>
                </div>
                <div class="ep-find-wrap">
                    <input type="number" class="ep-find-input" placeholder="Jump to ep…"
                        min="1" max="${allEps.length}"
                        onchange="jumpToEp(parseInt(this.value))">
                </div>
            </div>
            <div class="ep-num-grid">${cells}</div>
            <div class="ep-total">${allEps.length} episodes total</div>
        </div>`;
}

function changeEpPage(pageIndex) {
    if (!window._allEpisodes) return;
    const el = document.getElementById('episodeSection');
    if (el) el.innerHTML = buildEpGrid(
        window._allEpisodes, parseInt(pageIndex),
        window._currentEp, window._epPageSize
    );
}

function jumpToEp(num) {
    if (!window._allEpisodes) return;
    const total = window._allEpisodes.length;
    if (!num || num < 1 || num > total) return;
    const pageIndex = Math.floor((num - 1) / (window._epPageSize || 100));
    window._currentEp = num;
    const el = document.getElementById('episodeSection');
    if (el) el.innerHTML = buildEpGrid(
        window._allEpisodes, pageIndex, num, window._epPageSize
    );
    setTimeout(() => {
        const active = document.querySelector('.ep-active');
        if (active) active.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }, 50);
}

function selectEpisode(num) {
    window._currentEp = num;
    // Highlight selected cell (no external link — just mark active)
    document.querySelectorAll('.ep-cell').forEach(c => {
        c.classList.toggle('ep-active', parseInt(c.textContent.trim()) === num);
    });
}

// Run auth check and detail fetch in parallel - detail.js only redirects
// if auth fails, so both can fire simultaneously
Promise.all([checkAuth(), fetchDetail()]);

