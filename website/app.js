// ── RLScoreBot Website Interactive JavaScript ──────────────────────────────

let currentAudio = null;

// Search & Filter Commands
function filterCommands() {
    const input = document.getElementById('cmd-search').value.toLowerCase();
    const cards = document.querySelectorAll('.cmd-card');

    cards.forEach(card => {
        const text = card.textContent.toLowerCase();
        if (text.includes(input)) {
            card.style.display = 'flex';
        } else {
            card.style.display = 'none';
        }
    });
}

// Animated Counter Utility
function animateValue(element, start, end, duration) {
    if (start === end) return;
    let startTimestamp = null;
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        const current = Math.floor(progress * (end - start) + start);
        element.innerText = current.toLocaleString() + "+";
        if (progress < 1) {
            window.requestAnimationFrame(step);
        }
    };
    window.requestAnimationFrame(step);
}

// Fetch stats frequently from backend API (Handles GitHub Pages & Render seamlessly)
async function fetchStats() {
    try {
        const apiUrl = window.location.hostname.includes('github.io') 
            ? 'https://rlscorebot.onrender.com/api/v1/stats' 
            : '/api/v1/stats';

        const res = await fetch(apiUrl);
        if (res.ok) {
            const data = await res.json();
            
            const goalsEl = document.getElementById('stat-goals');
            const soundsEl = document.getElementById('stat-sounds');
            
            if (goalsEl && data.total_goals) {
                const currentVal = parseInt(goalsEl.innerText.replace(/[^0-9]/g, '')) || 506;
                if (currentVal !== data.total_goals) {
                    animateValue(goalsEl, currentVal, data.total_goals, 1000);
                } else {
                    goalsEl.innerText = data.total_goals.toLocaleString() + "+";
                }
            }
            
            if (soundsEl && data.total_sounds) {
                soundsEl.innerText = data.total_sounds.toLocaleString();
            }
        }
    } catch (err) {
        // Fallback gracefully to default stats
    }
}

// Initialize on Page Load
document.addEventListener('DOMContentLoaded', () => {
    fetchStats();
    setInterval(fetchStats, 5000);
});
