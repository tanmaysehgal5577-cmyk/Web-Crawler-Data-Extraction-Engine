document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('crawlForm');
    const startBtn = document.getElementById('startBtn');
    const statusBadge = document.getElementById('currentStatus');
    const statsGrid = document.getElementById('statsGrid');
    
    let pollInterval = null;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const url = document.getElementById('url').value;
        const depth = parseInt(document.getElementById('depth').value);

        startBtn.classList.add('loading');
        startBtn.disabled = true;

        try {
            const res = await fetch('/api/crawl', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, max_depth: depth })
            });
            const data = await res.json();
            
            if (data.error) {
                alert(data.error);
                startBtn.classList.remove('loading');
                startBtn.disabled = false;
                return;
            }

            startPolling();
        } catch (err) {
            console.error(err);
            startBtn.classList.remove('loading');
            startBtn.disabled = false;
        }
    });

    function startPolling() {
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(fetchStatus, 1000);
        fetchStatus();
    }

    async function fetchStatus() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();

            // Update Badge
            statusBadge.textContent = data.status.charAt(0).toUpperCase() + data.status.slice(1);
            statusBadge.className = `badge ${data.status.toLowerCase().replace(/error.*/, 'error')}`;

            // Update Stats
            if (data.stats && Object.keys(data.stats).length > 0) {
                statsGrid.innerHTML = '';
                for (const [key, value] of Object.entries(data.stats)) {
                    const card = document.createElement('div');
                    card.className = 'stat-card';
                    card.innerHTML = `<div class="stat-value">${value}</div><div class="stat-label">${key.replace(/_/g, ' ')}</div>`;
                    statsGrid.appendChild(card);
                }
            }

            if (data.status === 'completed' || data.status.startsWith('error')) {
                clearInterval(pollInterval);
                startBtn.classList.remove('loading');
                startBtn.disabled = false;
            }
        } catch (err) {
            console.error(err);
        }
    }

    // Search Logic
    const searchBtn = document.getElementById('searchBtn');
    const searchInput = document.getElementById('searchInput');
    const searchResults = document.getElementById('searchResults');

    searchBtn.addEventListener('click', async () => {
        const q = searchInput.value.trim();
        if (!q) return;

        searchBtn.textContent = '...';
        try {
            const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
            const data = await res.json();
            
            searchResults.innerHTML = '';
            if (data.results.length === 0) {
                searchResults.innerHTML = '<p>No results found.</p>';
            } else {
                data.results.forEach(r => {
                    const el = document.createElement('div');
                    el.className = 'result-card';
                    el.innerHTML = `
                        <h3>${r.title || 'Untitled'} (Score: ${r.score.toFixed(2)})</h3>
                        <a href="${r.url}" target="_blank">${r.url}</a>
                    `;
                    searchResults.appendChild(el);
                });
            }
        } catch (err) {
            console.error(err);
        }
        searchBtn.textContent = 'Search';
    });
});
