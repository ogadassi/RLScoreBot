// ── RLScoreBot Website Interactive JavaScript ──────────────────────────────

let currentAudio = null;

// Play Sound in Web Audio Player
function playSound(filename, title) {
    const player = document.getElementById('audio-player');
    const npBar = document.getElementById('now-playing-bar');
    const npTitle = document.getElementById('np-title');

    player.src = '/sounds/' + filename;
    player.play().then(() => {
        npTitle.innerText = title;
        npBar.classList.remove('hidden');
    }).catch(err => {
        console.warn("Audio playback fallback:", err);
        // Fallback for preview testing
        alert("Playing sound preview: " + title);
    });

    player.onended = () => {
        npBar.classList.add('hidden');
    };
}

function stopAudio() {
    const player = document.getElementById('audio-player');
    const npBar = document.getElementById('now-playing-bar');
    player.pause();
    player.currentTime = 0;
    npBar.classList.add('hidden');
}

// User Custom File Preview Tester
document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('sound-upload-input');
    if (fileInput) {
        fileInput.addEventListener('change', (event) => {
            const file = event.target.files[0];
            if (!file) return;

            const fileURL = URL.createObjectURL(file);
            const player = document.getElementById('audio-player');
            const npBar = document.getElementById('now-playing-bar');
            const npTitle = document.getElementById('np-title');

            player.src = fileURL;
            player.play().then(() => {
                npTitle.innerText = "Custom File: " + file.name + " (Testing -14 LUFS)";
                npBar.classList.remove('hidden');
            });

            player.onended = () => {
                npBar.classList.add('hidden');
            };
        });
    }

    // Fetch stats immediately and poll frequently every 5 seconds
    fetchStats();
    setInterval(fetchStats, 5000);
});

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

// Fetch stats frequently from backend API
async function fetchStats() {
    try {
        const res = await fetch('/api/v1/stats');
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
        // Silent fallback
    }
}
