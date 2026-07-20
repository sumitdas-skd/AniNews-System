// State management
let currentTab = 'anime';

// Initial Load
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    loadDashboard();
    loadAdminData();
    loadUsers();

    // Auto refresh stats every 30 seconds
    setInterval(loadDashboard, 30000);

    // Search on Enter
    const searchInput = document.getElementById('adminAnimeSearch');
    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') searchAdminAnime();
        });
    }
});

async function loadDashboard() {
    try {
        const response = await fetch('/api/admin/stats');
        const stats = await response.json();

        document.getElementById('onlineUsersCount').textContent = stats.online_users;
        document.getElementById('totalUsersCount').textContent = stats.total_users;
        document.getElementById('totalAnimeCount').textContent = stats.total_anime;
        document.getElementById('pendingAnimeCount').textContent = stats.pending_anime;
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

async function loadAdminData() {
    try {
        const searchInput = document.getElementById('adminAnimeSearch');
        const query = searchInput ? searchInput.value.trim() : '';

        const url = query ? `/api/admin/anime?search=${encodeURIComponent(query)}` : '/api/admin/anime';
        const response = await fetch(url);
        const data = await response.json();
        renderAdminTable(data);
    } catch (error) {
        console.error('Error loading anime data:', error);
    }
}

function searchAdminAnime() {
    loadAdminData();
}

async function loadUsers() {
    try {
        const response = await fetch('/api/admin/users');
        const users = await response.json();
        renderUsersTable(users);
    } catch (error) {
        console.error('Error loading users:', error);
    }
}

function renderAdminTable(animeList) {
    const tbody = document.getElementById('adminTableBody');
    tbody.innerHTML = '';

    animeList.forEach(anime => {
        const tr = document.createElement('tr');
        if (!anime.is_approved) tr.style.background = 'rgba(252, 176, 69, 0.05)';

        tr.innerHTML = `
            <td>
                <div style="font-weight: 600; color: white;">${anime.title}</div>
                <div style="font-size: 0.8rem; color: var(--text-dim);">ID: ${anime.anilist_id || 'Manual'}</div>
            </td>
            <td><span class="status-badge status-${anime.status}" style="font-size: 0.65rem; position: static;">${anime.status}</span></td>
            <td>${anime.release_date || 'TBA'}</td>
            <td>
                <span style="color: ${anime.is_approved ? '#10b981' : '#f59e0b'}; font-weight: 600; font-size: 0.9rem;">
                    ${anime.is_approved ? '✓ Approved' : '⏳ Pending'}
                </span>
            </td>
            <td>
                <div style="display: flex; gap: 0.5rem; align-items: center;">
                    ${!anime.is_approved ? `<button class="actions-btn" onclick="approve(${anime.id})">Approve</button>` : ''}
                    <button class="actions-btn" onclick="deleteAnime(${anime.id})" 
                        style="background: rgba(239, 68, 68, 0.1); color: #ef4444; border-color: rgba(239, 68, 68, 0.2);">Delete</button>
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function renderUsersTable(users) {
    const tbody = document.getElementById('usersTableBody');
    tbody.innerHTML = '';

    // Consider a user "online" if they were active in the last 5 minutes
    const now = new Date();

    users.forEach(user => {
        const lastSeen = user.last_seen ? new Date(user.last_seen) : null;
        const isOnline = lastSeen && (now - lastSeen) < 5 * 60 * 1000;

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>
                <div style="font-weight: 600; color: white;">${user.username || user.email.split('@')[0]}</div>
                <div style="font-size: 0.8rem; color: var(--text-dim);">${user.email}</div>
            </td>
            <td><span style="font-size: 0.8rem; background: rgba(255,255,255,0.05); padding: 0.2rem 0.5rem; border-radius: 4px;">${user.role}</span></td>
            <td>
                <div style="display: flex; align-items: center;">
                    <span class="${isOnline ? 'user-online-dot' : 'user-offline-dot'}"></span>
                    <span style="font-size: 0.85rem;">${isOnline ? 'Online' : 'Offline'}</span>
                </div>
            </td>
            <td>
                <div style="font-size: 0.85rem;">${formatLastSeen(lastSeen)}</div>
            </td>
            <td>
                <div style="font-size: 0.85rem; color: var(--text-dim);">${new Date(user.created_at).toLocaleDateString()}</div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function formatLastSeen(date) {
    if (!date) return 'Never';
    const now = new Date();
    const diff = Math.floor((now - date) / 1000);

    if (diff < 60) return 'Just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return date.toLocaleDateString();
}

function switchTab(tabName, btn) {
    currentTab = tabName;

    // Update UI
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    if (btn) btn.classList.add('active');

    document.getElementById('animeSection').classList.remove('active');
    const usersSec = document.getElementById('usersSection');
    if (usersSec) usersSec.classList.remove('active');

    const targetSec = document.getElementById(`${tabName}Section`);
    if (targetSec) targetSec.classList.add('active');

    if (tabName === 'users') loadUsers();
    else loadAdminData();
}

async function approve(id) {
    const isConfirmed = window.confirm('Are you sure you want to APPROVE this anime for public display?');
    if (isConfirmed) {
        const response = await fetch(`/api/admin/approve/${id}`, { method: 'POST' });
        if (response.ok) {
            alert('Anime approved!');
            loadAdminData();
            loadDashboard();
        }
    }
}

async function deleteAnime(id) {
    const isConfirmed = window.confirm('⚠️ CRITICAL: Are you sure you want to PERMANENTLY delete this anime? This cannot be undone.');
    if (isConfirmed) {
        const response = await fetch(`/api/admin/anime/${id}`, { method: 'DELETE' });
        if (response.ok) {
            alert('Anime deleted successfully.');
            loadAdminData();
            loadDashboard();
        } else {
            alert('Failed to delete anime.');
        }
    }
}

async function triggerUpdate(btn) {
    const originalText = btn.textContent;
    btn.textContent = 'Syncing...';
    btn.disabled = true;

    try {
        await fetch('/api/admin/force-update', { method: 'POST' });
        alert('Database sync completed successfully!');
    } catch (e) {
        alert('Sync failed. Check logs.');
    } finally {
        btn.textContent = originalText;
        btn.disabled = false;
        loadAdminData();
        loadDashboard();
    }
}

function openModal() {
    document.getElementById('addModal').style.display = 'flex';
}

function closeModal() {
    document.getElementById('addModal').style.display = 'none';
}

async function checkAuth() {
    try {
        const response = await fetch('/api/auth/me');
        const data = await response.json();
        const profileDiv = document.getElementById('userProfile');

        if (data.status === 'success') {
            profileDiv.innerHTML = `
                <span class="user-email" style="margin-right: 1rem; opacity: 0.8;">👤 ${data.user.email}</span>
                <a href="javascript:void(0)" onclick="logout(event)" style="color: var(--admin-primary); text-decoration: none; font-weight: 600;">🚪 Logout</a>
            `;
            return true;
        } else {
            window.location.href = '/login';
            return false;
        }
    } catch (err) {
        window.location.href = '/login';
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

document.getElementById('addForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = {
        title: document.getElementById('m_title').value,
        release_date: document.getElementById('m_date').value,
        status: document.getElementById('m_status').value,
        poster_url: document.getElementById('m_poster').value,
        description: document.getElementById('m_desc').value,
        genres: document.getElementById('m_genres').value,
        platform_name: document.getElementById('m_platform').value,
        streaming_url: document.getElementById('m_streaming').value
    };

    const response = await fetch('/api/admin/manual-add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });

    if (response.ok) {
        closeModal();
        loadAdminData();
        loadDashboard();
        alert('Anime added and notification sent!');
    }
});
