if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(err => console.log('SW registration failed:', err));
    });
}

let currentMode = 'home';
let currentPage = 0;
let authCache = null;
const PAGE_SIZE = 20;
const genreList = [
    "Action & Adventure", "Slice of Life", "Fantasy", "Dark Fantasy", "Sci-Fi & Mecha",
    "Romance", "Supernatural & Horror", "Sports", "Isekai", "Mahou Shoujo",
    "Iyashikei", "Harem / Reverse Harem", "Ecchi", "Trending"
];
let lastFetchId = 0;

// Debounce helper to prevent slamming the server
function debounce(func, timeout = 300) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => { func.apply(this, args); }, timeout);
    };
}

async function checkAuth() {
    try {
        const response = await fetch('/api/auth/me');
        const data = await response.json();
        const profileDiv = document.getElementById('userProfile');

        if (data.status === 'success') {
            authCache = true;
            profileDiv.innerHTML = `
                <span class="user-email">👤 ${data.user.email}</span>
                <a href="javascript:void(0)" onclick="logout(event)" class="logout-link">🚪 Logout</a>
            `;
            const adminLink = document.getElementById('adminLink');
            if (adminLink && data.user.role === 'admin') adminLink.style.display = 'flex';
            return true;
        } else {
            authCache = false;
            if (window.location.pathname !== '/login') {
                window.location.replace('/login');
            }
            return false;
        }
    } catch (err) {
        authCache = false;
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
        authCache = false;
        window.location.href = '/login';
    } catch (err) {
        console.error('Logout failed', err);
        location.reload();
    }
}

async function fetchAnime(mode = null, append = false, reset = false) {
    const thisFetchId = ++lastFetchId;
    if (mode === '') mode = 'home'; // Reset to home if empty string (All Genres)
    if (mode) currentMode = mode;

    if (!append) {
        currentPage = 0;
        const grid = document.getElementById('animeGrid');
        if (grid) grid.innerHTML = '<div class="loading">Loading Latest Anime...</div>';

        if (reset || currentMode === 'reset') {
            document.getElementById('searchInput').value = '';
            document.getElementById('statusFilter').value = '';
            document.getElementById('categoryFilter').value = '';
            if (currentMode === 'reset') currentMode = 'home';
        }
    }

    const countryMap = { "Korean": "KR", "Chinese": "CN", "Japanese": "JP" };

    // Synchronize the category dropdown with the current mode
    const catFilter = document.getElementById('categoryFilter');
    if (genreList.includes(currentMode)) {
        catFilter.value = currentMode;
    } else if (countryMap[currentMode]) {
        catFilter.value = currentMode;
    } else if (currentMode === 'home' || currentMode === 'trending' || currentMode === 'watchlist') {
        catFilter.value = '';
    }

    const search = document.getElementById('searchInput').value;
    const status = document.getElementById('statusFilter').value;
    const category = document.getElementById('categoryFilter').value;

    const queryParams = new URLSearchParams();
    queryParams.set('limit', PAGE_SIZE);
    queryParams.set('offset', currentPage * PAGE_SIZE);
    queryParams.set('mode', currentMode);

    if (search) queryParams.set('search', search);
    if (status) queryParams.set('status', status);
    if (category) {
        if (countryMap[category]) queryParams.set('country', countryMap[category]);
        else queryParams.set('category', category);
    }

    const url = `/api/anime?${queryParams.toString()}`;

    // Update Browser History (Push state only if NOT from a back/forward button)
    if (!append && arguments[3] !== 'popstate') {
        const stateUrl = `/?${queryParams.toString()}`;
        if (reset) history.replaceState({ mode: currentMode, search, status, category }, '', stateUrl);
        else history.pushState({ mode: currentMode, search, status, category }, '', stateUrl);
    }

    try {
        const response = await fetch(url);
        const data = await response.json();

        // If a new request has been fired since this one started, discard this result
        if (thisFetchId !== lastFetchId) return;

        renderGrid(data, append);
        updateActiveLink(currentMode);

        const loadMoreBtn = document.getElementById('loadMoreBtn');
        if (loadMoreBtn) {
            loadMoreBtn.style.display = data.length < PAGE_SIZE ? 'none' : 'inline-block';
        }
    } catch (error) {
        console.error('Error fetching anime:', error);
        if (!append && thisFetchId === lastFetchId) renderGrid([]);
    }
}

function loadMore() {
    currentPage++;
    fetchAnime(currentMode, true);
}

function updateActiveLink(mode) {
    document.querySelectorAll('.sidebar nav a').forEach(a => {
        a.classList.remove('active');
        if (a.getAttribute('data-mode') === mode) a.classList.add('active');
    });
}

async function renderGrid(animeList, append = false) {
    const grid = document.getElementById('animeGrid');
    if (!append) grid.innerHTML = '';

    // Remove loading indicator if present
    const loader = grid.querySelector('.loading');
    if (loader) loader.remove();

    const isLoggedIn = authCache !== null ? authCache : await checkAuthSilent();

    if (!append && animeList.length === 0) {
        if (currentMode === 'watchlist') {
            grid.innerHTML = `
                <div class="no-results">
                    <div class="no-results-icon">🔖</div>
                    <h3>Your List is Empty</h3>
                    <p>You haven't added any anime to your list yet. Browse the home page and click the plus icon to save your favorites!</p>
                    <button onclick="fetchAnime('home', false, true)" style="margin-top: 1rem;">Browse Anime</button>
                </div>
            `;
        } else {
            grid.innerHTML = `
                <div class="no-results">
                    <div class="no-results-icon">🔍</div>
                    <h3>No result found.</h3>
                    <p>We couldn't find any anime matching your criteria. Try adjusting your filters or search terms.</p>
                </div>
            `;
        }
        return;
    }

    animeList.forEach(anime => {
        const card = document.createElement('div');
        card.className = 'anime-card';

        const genres = anime.genres ? anime.genres.split(',').slice(0, 3) : [];
        const genreHtml = genres.map(g => `<span class="genre-tag">${g}</span>`).join('');

        let ratingHtml = '';
        if (anime.rating_score) {
            ratingHtml = `<span class="grid-rating">⭐ ${anime.rating_score.toFixed(1)}</span>`;
        } else if (anime.status === 'Upcoming') {
            const releaseDate = anime.release_date && anime.release_date !== 'TBA' ? new Date(anime.release_date) : null;
            const today = new Date();
            if (releaseDate && releaseDate <= today) {
                ratingHtml = `<span class="grid-rating">Rating not available</span>`;
            } else {
                ratingHtml = `<span class="grid-rating status-upcoming-text">Upcoming</span>`;
            }
        } else {
            ratingHtml = `<span class="grid-rating">Rating not available</span>`;
        }

        let epInfo = '';
        if (anime.status === 'Ongoing') {
            epInfo = `EP ${anime.episodes_current || 0} / ${anime.episodes_total || '?'}`;
        } else if (anime.status === 'Completed') {
            epInfo = `${anime.episodes_total || '?'} Episodes`;
        }

        const lastEpName = anime.last_episode_name ? `<p class="last-ep">Latest: ${anime.last_episode_name}</p>` : '';

        card.innerHTML = `
            <a href="/detail.html?id=${anime.id}" class="card-link">
                <div class="card-inner">
                    <span class="status-badge status-${anime.status}">${anime.status}</span>
                    <img src="${anime.poster_url}" alt="${anime.title}" class="poster" loading="lazy" onerror="this.src='https://via.placeholder.com/280x400?text=No+Poster'">
                    <div class="card-content">
                        <div class="meta-top">
                            ${ratingHtml}
                            <span class="release-date">📅 ${anime.release_date || 'TBA'}</span>
                        </div>
                        <h3>${anime.title}</h3>
                        <div class="ep-badge">${epInfo}</div>
                        ${lastEpName}
                        <div class="genre-list">${genreHtml}</div>
                        <div class="description">
                            <div class="description-text">${anime.description ? anime.description.substring(0, 80) + '...' : 'No description available.'}</div>
                        </div>
                    </div>
                </div>
            </a>
            <button class="watchlist-btn" onclick="toggleWatchlist(event, ${anime.id})" id="watchlist-btn-${anime.id}" title="${currentMode === 'watchlist' ? 'Remove from List' : 'Add to My List'}">
                ${currentMode === 'watchlist' ? '➖' : '➕'}
            </button>
        `;
        grid.appendChild(card);
    });
}

// Added checkAuthSilent to avoid redirect loop during rendering
async function checkAuthSilent() {
    try {
        const response = await fetch('/api/auth/me');
        const data = await response.json();
        return data.status === 'success';
    } catch {
        return false;
    }
}

async function toggleReviewPanel(animeId, btn) {
    const panel = document.getElementById(`reviews-${animeId}`);
    panel.classList.toggle('active');

    if (panel.classList.contains('active')) {
        fetchReviews(animeId);
    }
}

function toggleDescription(animeId) {
    const container = document.getElementById(`desc-container-${animeId}`);
    const btn = container.querySelector('.read-more-btn');
    container.classList.toggle('expanded');
    btn.textContent = container.classList.contains('expanded') ? 'Read Less' : 'Read More';
}

async function fetchReviews(animeId) {
    const list = document.querySelector(`#reviews-${animeId} .reviews-list`);
    try {
        const response = await fetch(`/api/reviews/${animeId}`);
        const reviews = await response.json();

        if (reviews.length === 0) {
            list.innerHTML = '<p style="font-size:0.8rem; margin:1rem 0;">No reviews yet. Be the first!</p>';
            return;
        }

        list.innerHTML = reviews.map(r => `
            <div class="review-item">
                <div class="review-header">
                    <strong>${r.username}</strong>
                    <span class="rating-stars">${'⭐'.repeat(r.rating)}</span>
                </div>
                <p class="review-comment">${r.comment}</p>
            </div>
        `).join('');
    } catch (error) {
        list.innerHTML = 'Error loading reviews.';
    }
}

async function submitReview(event, animeId) {
    event.preventDefault();
    const form = event.target;
    const data = {
        username: form.querySelector('.rev-name').value,
        rating: parseInt(form.querySelector('.rev-rating').value),
        comment: form.querySelector('.rev-comment').value
    };

    try {
        await fetch(`/api/reviews/${animeId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        form.reset();
        form.classList.remove('active');
        fetchReviews(animeId);
    } catch (error) {
        alert('Failed to post review.');
    }
}

// Push Notifications logic
async function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
        try {
            const register = await navigator.serviceWorker.register('/sw.js');
            console.log('Service Worker Registered');

            const banner = document.getElementById('notifyBanner');
            const permission = await Notification.requestPermission();

            if (permission === 'granted') {
                banner.style.display = 'none';
                subscribeUser(register);
            } else if (permission === 'default') {
                banner.style.display = 'block';
                banner.onclick = () => registerServiceWorker();
            }
        } catch (error) {
            console.error('Service Worker registration failed:', error);
        }
    }
}

async function subscribeUser(register) {
    let subscription = await register.pushManager.getSubscription();

    if (!subscription) {
        const response = await fetch('/api/vapid-public-key');
        const { publicKey } = await response.json();

        subscription = await register.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(publicKey)
        });

        await fetch('/api/subscribe', {
            method: 'POST',
            body: JSON.stringify(subscription),
            headers: { 'Content-Type': 'application/json' }
        });
    }
}

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

async function setReminder(animeId) {
    try {
        const response = await fetch('/api/reminders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ anime_id: animeId })
        });
        const data = await response.json();
        alert(data.message);
    } catch (error) {
        alert('Failed to set reminder.');
    }
}

// Search Features
const searchInput = document.getElementById('searchInput');
const clearSearchBtn = document.getElementById('clearSearchBtn');


clearSearchBtn.addEventListener('click', () => {
    searchInput.value = '';
    fetchAnime(currentMode);
});


// Listeners
const debouncedSearch = debounce(() => fetchAnime(currentMode), 350);
searchInput.addEventListener('input', debouncedSearch);
document.getElementById('statusFilter').addEventListener('change', () => fetchAnime());
document.getElementById('categoryFilter').addEventListener('change', (e) => {
    // If selecting All Genres from dropdown, we want to go back to home mode
    const val = e.target.value;
    fetchAnime(val === '' ? 'home' : val);
});

async function toggleWatchlist(event, animeId) {
    if (event) event.stopPropagation();
    event.preventDefault();

    const btn = document.getElementById(`watchlist-btn-${animeId}`);
    const isRemove = btn.textContent.trim() === '➖';

    try {
        const response = await fetch('/api/watchlist', {
            method: isRemove ? 'DELETE' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ anime_id: animeId })
        });
        const data = await response.json();

        if (data.status === 'success') {
            if (currentMode === 'watchlist') {
                fetchAnime('watchlist'); // Refresh list if we are in My List view
            } else {
                btn.textContent = isRemove ? '➕' : '➖';
                btn.title = isRemove ? 'Add to My List' : 'Remove from List';
            }
        } else if (data.message === 'Login required') {
            window.location.href = '/login';
        }
    } catch (err) {
        console.error('Watchlist update failed');
    }
}


window.onpopstate = function (event) {
    if (event.state) {
        const { mode, search, status, category } = event.state;
        document.getElementById('searchInput').value = search || '';
        document.getElementById('statusFilter').value = status || '';
        document.getElementById('categoryFilter').value = category || '';
        fetchAnime(mode, false, false, 'popstate');
    } else {
        fetchAnime('home', false, true, 'popstate');
    }
};

// Permission Logic
async function checkFirstLogin() {
    // If permissions are already configured, never show the modal again
    if (localStorage.getItem('permissions_configured') === 'true') {
        return;
    }

    if (localStorage.getItem('first_login') === 'true') {
        localStorage.removeItem('first_login');

        // Check current status to reflect in UI
        const calBtn = document.getElementById('calPermBtn');


        // Reflect Calendar status if previously enabled
        if (localStorage.getItem('calendar_enabled') === 'true' && calBtn) {
            calBtn.textContent = 'Enabled ✓';
            calBtn.classList.add('allowed');
            calBtn.onclick = null;
        }

        document.getElementById('permissionModal').style.display = 'flex';
    }
}


function requestCalendarPermission() {
    // Browsers don't have a native 'write-to-OS-calendar' API.
    // We request 'permission' to enable the optimized calendar feature.
    const btn = document.getElementById('calPermBtn');
    btn.textContent = 'Enabled ✓';
    btn.classList.add('allowed');
    btn.onclick = null;
    localStorage.setItem('calendar_enabled', 'true');
}

function closePermissions() {
    localStorage.setItem('permissions_configured', 'true');
    document.getElementById('permissionModal').style.display = 'none';
}

// Consolidated Init — single auth check, then first fetch
(async function init() {
    await checkAuth(); // Ensures authCache is populated before first fetch
    fetchAnime('home', false, true);
    registerServiceWorker();
    checkFirstLogin();
})();
