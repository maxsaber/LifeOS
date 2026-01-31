// Enhanced CRM JavaScript - Patch for infinite scroll, filters, and badges
// This should replace the existing script section in crm.html

// State
let people = [];
let allPeople = [];
let selectedPersonId = null;
let currentCategoryFilter = 'all';
let currentSourceFilters = [];
let currentMinStrength = 0.0;
let currentSort = 'last_seen';
let searchQuery = '';
let offset = 0;
let hasMore = false;
let isLoading = false;
let filtersCollapsed = true;
let availableSources = [];

// Source badge mapping
const sourceBadges = {
    'gmail': '📧',
    'calendar': '📅',
    'slack': '💬',
    'vault': '📝',
    'contacts': '👤',
    'imessage': '💭',
    'linkedin': '💼',
    'whatsapp': '📱',
    'signal': '🔐'
};

// API helpers
async function api(path, options = {}) {
    const response = await fetch(`/api/crm${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options
    });
    if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
    }
    return response.json();
}

// Initialize
async function init() {
    await loadStatistics();
    await loadSourceFilters();
    await loadPeople();
    setupInfiniteScroll();
}

// Load available sources for filters
async function loadSourceFilters() {
    try {
        const data = await api('/statistics');
        availableSources = Object.keys(data.by_source || {}).filter(s => s);
        renderSourceFilters();
    } catch (error) {
        console.error('Failed to load source filters:', error);
    }
}

// Render source filter checkboxes
function renderSourceFilters() {
    const container = document.getElementById('sourceFilters');
    if (!container) return;

    if (availableSources.length === 0) {
        container.innerHTML = '<div style="font-size:0.7rem;color:var(--text-muted)">No sources available</div>';
        return;
    }

    container.innerHTML = availableSources.map(source => `
        <label class="filter-checkbox">
            <input type="checkbox" value="${source}" onchange="updateSourceFilters()">
            <span>${sourceBadges[source] || '📋'} ${source}</span>
        </label>
    `).join('');
}

// Toggle filters panel
function toggleFilters() {
    const panel = document.getElementById('filterPanel');
    const icon = document.getElementById('filterToggleIcon');
    if (!panel || !icon) return;

    filtersCollapsed = !filtersCollapsed;

    if (filtersCollapsed) {
        panel.classList.add('collapsed');
        icon.textContent = '▶';
    } else {
        panel.classList.remove('collapsed');
        icon.textContent = '▼';
    }
}

// Update source filters
function updateSourceFilters() {
    const checkboxes = document.querySelectorAll('#sourceFilters input[type="checkbox"]:checked');
    currentSourceFilters = Array.from(checkboxes).map(cb => cb.value);
    resetAndLoadPeople();
}

// Update strength filter
function updateStrengthFilter() {
    const slider = document.getElementById('strengthSlider');
    if (!slider) return;

    currentMinStrength = parseFloat(slider.value) / 100;
    const valueEl = document.getElementById('strengthValue');
    if (valueEl) {
        valueEl.textContent = currentMinStrength.toFixed(2);
    }
    resetAndLoadPeople();
}

// Update sort
function updateSort() {
    const select = document.getElementById('sortSelect');
    if (!select) return;

    currentSort = select.value;
    resetAndLoadPeople();
}

// Set category filter
function setCategoryFilter(category) {
    currentCategoryFilter = category;

    // Update UI
    document.querySelectorAll('[data-filter]').forEach(c => c.classList.remove('active'));
    const chip = document.querySelector(`[data-filter="${category}"]`);
    if (chip) chip.classList.add('active');

    resetAndLoadPeople();
}

// Reset and reload people (for filter changes)
function resetAndLoadPeople() {
    offset = 0;
    people = [];
    allPeople = [];
    loadPeople();
}

// Setup infinite scroll
function setupInfiniteScroll() {
    const listEl = document.getElementById('peopleList');
    if (!listEl) return;

    listEl.addEventListener('scroll', () => {
        if (isLoading || !hasMore) return;

        const scrollTop = listEl.scrollTop;
        const scrollHeight = listEl.scrollHeight;
        const clientHeight = listEl.clientHeight;

        // Load more when within 200px of bottom
        if (scrollTop + clientHeight >= scrollHeight - 200) {
            loadMorePeople();
        }
    });
}

// Load people list
async function loadPeople() {
    if (isLoading) return;
    isLoading = true;

    const listEl = document.getElementById('peopleList');
    if (!listEl) return;

    if (offset === 0) {
        listEl.innerHTML = '<div class="loading">Loading people...</div>';
    } else {
        const loader = document.createElement('div');
        loader.className = 'scroll-loader';
        loader.textContent = 'Loading more...';
        loader.id = 'scrollLoader';
        listEl.appendChild(loader);
    }

    try {
        const params = new URLSearchParams();
        if (searchQuery) params.set('q', searchQuery);
        if (currentCategoryFilter !== 'all') {
            params.set('category', currentCategoryFilter);
        }
        params.set('sort', currentSort);
        params.set('offset', offset.toString());
        params.set('limit', '50');

        const data = await api(`/people?${params}`);

        // Apply client-side filters for sources and strength
        let filteredPeople = data.people;

        if (currentSourceFilters.length > 0) {
            filteredPeople = filteredPeople.filter(p =>
                p.sources && p.sources.some(s => currentSourceFilters.includes(s))
            );
        }

        if (currentMinStrength > 0) {
            filteredPeople = filteredPeople.filter(p =>
                (p.relationship_strength || 0) >= currentMinStrength
            );
        }

        if (offset === 0) {
            people = filteredPeople;
            allPeople = filteredPeople;
        } else {
            people = [...people, ...filteredPeople];
            allPeople = [...allPeople, ...filteredPeople];
            // Remove scroll loader
            const loader = document.getElementById('scrollLoader');
            if (loader) loader.remove();
        }

        offset += 50;
        hasMore = data.has_more;

        renderPeopleList();
    } catch (error) {
        console.error('Failed to load people:', error);
        if (offset === 0) {
            listEl.innerHTML = '<div class="empty-state"><div class="empty-state-icon">⚠️</div><p>Failed to load people</p></div>';
        }
    } finally {
        isLoading = false;
    }
}

// Load more people (infinite scroll)
async function loadMorePeople() {
    if (!hasMore || isLoading) return;
    await loadPeople();
}

// Load statistics
async function loadStatistics() {
    try {
        const data = await api('/statistics');
        const totalEl = document.getElementById('totalPeople');
        const pendingEl = document.getElementById('pendingLinks');

        if (totalEl) totalEl.textContent = data.total_people;
        if (pendingEl) pendingEl.textContent = data.pending_links_count;

        const badge = document.getElementById('pendingBadge');
        if (badge) {
            if (data.pending_links_count > 0) {
                badge.textContent = data.pending_links_count;
                badge.style.display = 'inline-flex';
            } else {
                badge.style.display = 'none';
            }
        }
    } catch (error) {
        console.error('Failed to load statistics:', error);
    }
}

// Render people list
function renderPeopleList() {
    const listEl = document.getElementById('peopleList');
    if (!listEl) return;

    if (people.length === 0 && !isLoading) {
        listEl.innerHTML = '<div class="empty-state"><div class="empty-state-icon">👥</div><p>No people found</p></div>';
        return;
    }

    const cards = people.map(person => `
        <div class="person-card ${person.id === selectedPersonId ? 'selected' : ''}"
             onclick="selectPerson('${person.id}')">
            <div class="person-avatar">${getInitials(person.canonical_name)}</div>
            <div class="person-info">
                <div class="person-name">${escapeHtml(person.canonical_name)}</div>
                <div class="person-company">${escapeHtml(person.company || person.position || '')}</div>
                <div class="person-meta">
                    <div class="person-badges">
                        ${(person.sources || []).slice(0, 4).map(s =>
                            `<span class="person-source-badge">${sourceBadges[s] || '📋'}</span>`
                        ).join('')}
                    </div>
                    <span class="person-last-seen">${formatDate(person.last_seen)}</span>
                </div>
            </div>
            <div class="person-strength">
                <div class="person-strength-bar" style="width: ${(person.relationship_strength || 0) * 100}%"></div>
            </div>
        </div>
    `).join('');

    if (offset === 50 || !listEl.querySelector('.person-card')) {
        listEl.innerHTML = cards;
    } else {
        // Remove loader before appending
        const loader = document.getElementById('scrollLoader');
        if (loader) loader.remove();
        listEl.insertAdjacentHTML('beforeend', cards);
    }

    // Add scroll loader if there are more items
    if (hasMore && !document.getElementById('scrollLoader')) {
        const loader = document.createElement('div');
        loader.className = 'scroll-loader';
        loader.id = 'scrollLoader';
        loader.textContent = 'Scroll for more...';
        listEl.appendChild(loader);
    }
}

// Handle search
let searchTimeout;
function handleSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        const input = document.getElementById('searchInput');
        if (input) {
            searchQuery = input.value;
            resetAndLoadPeople();
        }
    }, 300);
}

// Refresh data
async function refreshData() {
    await loadStatistics();
    await loadSourceFilters();
    resetAndLoadPeople();
    if (selectedPersonId) {
        await loadPersonDetail(selectedPersonId);
    }
}

// Utility functions
function getInitials(name) {
    if (!name) return '?';
    const parts = name.split(' ').filter(p => p.length > 0);
    if (parts.length === 0) return '?';
    if (parts.length === 1) return parts[0][0].toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateStr) {
    if (!dateStr) return 'Never';
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now - date;

    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
    if (diff < 86400000 && date.toDateString() === now.toDateString()) {
        return Math.floor(diff / 3600000) + 'h ago';
    }

    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (date.toDateString() === yesterday.toDateString()) {
        return 'Yesterday';
    }

    return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
    });
}

// Initialize on load
init();
