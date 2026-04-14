let currentAnime = null;

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

    // Ratings Star UI
    const score = anime.rating_score || 0;
    const stars = '⭐'.repeat(Math.round(score / 2)) + '☆'.repeat(5 - Math.round(score / 2));

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

    // Episodes List from relational list
    let episodeHtml = '';
    const episodes = anime.episodes_list || [];
    if (episodes.length > 0) {
        episodeHtml = `
            <div class="episodes-section">
                <h3>Episode List</h3>
                <div class="episodes-grid">
                    ${episodes.map(ep => `<div class="episode-item" title="${ep.episode_name || ''}">EP ${ep.episode_number}<br><small style="font-size:0.7rem;">${ep.episode_name || ''}</small></div>`).join('')}
                </div>
            </div>
        `;
    } else if (anime.status === 'Completed' || anime.status === 'Ongoing') {
        const total = anime.episodes_total || 0;
        if (total > 0) {
            if (total > 100) {
                episodeHtml = `
                    <div class="episodes-section">
                        <h3>Episode List</h3>
                        <p style="color: var(--text-dim); margin-bottom: 1rem;">This series has ${total} episodes. Browsing the full list may slow down your experience.</p>
                        <button class="view-btn" onclick="this.nextElementSibling.style.display='grid'; this.remove()">View All ${total} Episodes</button>
                        <div class="episodes-grid" style="display: none;">
                            ${Array.from({ length: total }, (_, i) => `<div class="episode-item">EP ${i + 1}</div>`).join('')}
                        </div>
                    </div>
                `;
            } else {
                episodeHtml = `
                    <div class="episodes-section">
                        <h3>Episode List</h3>
                        <div class="episodes-grid">
                            ${Array.from({ length: total }, (_, i) => `<div class="episode-item">EP ${i + 1}</div>`).join('')}
                        </div>
                    </div>
                `;
            }
        }
    }

    // Comments Section (Only for released anime)
    let reviewsHtml = '';
    if (anime.status !== 'Upcoming') {
        reviewsHtml = `
            <div class="reviews-section">
                <h3>Comments</h3>
                <div id="reviewsList">Loading comments...</div>
                <div class="add-review-form" style="margin-top: 2rem; background: var(--glass-bg); padding: 1.5rem; border-radius: 15px;">
                    <div style="margin-bottom: 1rem; display: flex; align-items: center; gap: 1rem;">
                        <span style="color: var(--text-dim);">Your Rating:</span>
                        <select id="ratingInput" style="padding: 0.5rem; border-radius: 5px; background: rgba(255,255,255,0.1); color: white; border: 1px solid var(--glass-border);">
                            <option value="5">⭐⭐⭐⭐⭐ (Excellent)</option>
                            <option value="4">⭐⭐⭐⭐ (Good)</option>
                            <option value="3">⭐⭐⭐ (Average)</option>
                            <option value="2">⭐⭐ (Poor)</option>
                            <option value="1">⭐ (Terrible)</option>
                        </select>
                    </div>
                    <textarea id="commentInput" placeholder="Write a comment..." style="width:100%; height:100px; padding:1rem; border-radius:10px; background: rgba(255,255,255,0.05); color:white; border:1px solid var(--glass-border); margin-bottom:1rem;"></textarea>
                    <button class="view-btn" style="padding:0.8rem 2rem;" onclick="submitComment()">Post Comment</button>
                </div>
            </div>
        `;
    } else {
        reviewsHtml = `
            <div class="reviews-section" style="opacity: 0.6;">
                <h3>Comments</h3>
                <p>Comments will be enabled once the first episode is released.</p>
            </div>
        `;
    }

    // Streaming Platforms section
    let streamingHtml = '';
    const platforms = anime.streaming_platforms || [];
    if (platforms.length > 0) {
        streamingHtml = `
            <div class="streaming-section">
                <h3>Where to Watch</h3>
                <div class="streaming-links" style="display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 1rem;">
                    ${platforms.map(p => `
                        <a href="${p.url}" target="_blank" class="streaming-btn">
                            📺 ${p.platform_name}
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

    const reminderBtn = anime.status === 'Completed' ? '' : `<button class="reminder-btn" style="width:100%; padding:1rem;" onclick="openReminderModal()">🔔 Remind Me</button>`;

    container.innerHTML = `
        <div class="detail-sidebar">
            <img src="${anime.poster_url}" class="detail-poster" alt="${anime.title}">
            
            <div style="margin-top: 2rem;">
                <span class="status-badge status-${anime.status}" style="margin-bottom: 0.5rem; display: inline-block;">${anime.status}</span>
                <h1 style="font-size: 2rem; margin-bottom: 1rem; line-height: 1.2;">${anime.title}</h1>
                <div class="meta-row" style="flex-direction: column; gap: 0.5rem; align-items: flex-start; margin-bottom: 1rem;">
                    <span class="meta-item">🏢 ${anime.studio || 'Unknown'}</span>
                    <span class="meta-item">📺 ${anime.episodes_total || 'TBA'} Episodes</span>
                    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                        ${genreHtml}
                    </div>
                </div>
            </div>

            <div class="rating-box" style="margin: 1.5rem 0;">
                <div class="rating-score">${score ? score.toFixed(1) : '—'}</div>
                <div>
                    <div style="color: #facc15;">${stars}</div>
                    <p style="color: var(--text-dim); font-size: 0.8rem;">${ratingDisplay}</p>
                </div>
            </div>

            ${countdownHtml}
            ${reminderBtn}
            
            <button id="watchlistDetailBtn" class="reminder-btn" style="width:100%; padding:1rem; margin-top: 1rem; border-color: var(--primary); color: var(--primary);" onclick="toggleWatchlistDetail(${anime.id})">
                🔖 Add to My List
            </button>
        </div>

        <div class="detail-info">
            <div class="streaming-section">
                ${streamingHtml}
            </div>

            <div style="margin-top: 3rem;">
                <div class="description">
                    <h3>Synopsis</h3>
                    <p style="line-height:1.8; margin-top:1.2rem;">${anime.description || 'No synopsis available.'}</p>
                </div>
            </div>

            <div style="margin-top: 3rem;">
                ${episodeHtml}
            </div>

            <div style="margin-top: 3rem;">
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
        const related = await response.json();

        if (related.length === 0) {
            const sidebar = document.querySelector('.detail-info');
            const section = document.createElement('div');
            section.style.marginTop = '3rem';
            section.innerHTML = '<h3>Related Anime</h3><p style="color: var(--text-dim); margin-top: 1rem;">No related anime available.</p>';
            sidebar.appendChild(section);
            return;
        }

        const sidebar = document.querySelector('.detail-info');
        const section = document.createElement('div');
        section.className = 'related-section';
        section.innerHTML = `
            <h3 style="margin-top: 3rem;">Related Anime</h3>
            <div class="related-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 1rem; margin-top: 1.5rem;">
                ${related.map(a => `
                    <a href="/detail.html?id=${a.id}" class="card-link">
                        <div class="anime-card compact" style="animation: none; margin:0;">
                            <span class="status-badge" style="font-size: 0.6rem; padding: 0.2rem 0.5rem;">${a.status}</span>
                            <img src="${a.poster_url}" style="height:200px; width:100%; object-fit:cover; border-radius:10px;">
                            <div style="padding: 0.5rem;">
                                <h4 style="font-size: 0.85rem; margin-bottom: 0.3rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${a.title}</h4>
                                <span style="color: #facc15; font-size: 0.75rem;">⭐ ${a.rating_score ? a.rating_score.toFixed(1) : (a.status === 'Upcoming' ? 'Upcoming' : 'Rating not available')}</span>
                            </div>
                        </div>
                    </a>
                `).join('')}
            </div>
        `;
        sidebar.appendChild(section);
    } catch (error) {
        console.error('Related fetch failed');
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
    document.getElementById('reminderModal').style.display = 'block';
}

function closeReminderModal() {
    document.getElementById('reminderModal').style.display = 'none';
}

async function reminderOptionA() {
    if (localStorage.getItem('calendar_enabled') === 'true') {
        const protocol = window.location.protocol === 'https:' ? 'webcals:' : 'webcal:';
        const calendarUrl = `${protocol}//${window.location.host}/api/calendar/${currentAnime.id}.ics`;

        // This browser-level protocol redirect opens the native System Calendar 
        // directly (Safari, Chrome, etc. all support this for direct marking).
        window.location.href = calendarUrl;
    } else {
        const title = currentAnime.title;
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
    if (event.target == modal) closeReminderModal();
}

async function checkWatchlist(animeId) {
    try {
        const response = await fetch(`/api/watchlist/check/${animeId}`);
        const data = await response.json();
        const btn = document.getElementById('watchlistDetailBtn');
        if (data.in_watchlist) {
            btn.innerHTML = '🔖 Remove from My List';
        }
    } catch (err) { }
}

async function toggleWatchlistDetail(animeId) {
    const btn = document.getElementById('watchlistDetailBtn');
    const isRemove = btn.innerHTML.includes('Remove');

    try {
        const response = await fetch('/api/watchlist', {
            method: isRemove ? 'DELETE' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ anime_id: animeId })
        });
        const data = await response.json();
        if (data.status === 'success') {
            btn.innerHTML = isRemove ? '🔖 Add to My List' : '🔖 Remove from My List';
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

// Run auth check and detail fetch in parallel - detail.js only redirects
// if auth fails, so both can fire simultaneously
Promise.all([checkAuth(), fetchDetail()]);
