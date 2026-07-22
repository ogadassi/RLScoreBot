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
        // Fallback for local preview testing
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

    // Dynamic stats counter fetch
    fetchStats();
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

// Fetch stats from backend API
async function fetchStats() {
    try {
        const res = await fetch('/api/v1/stats');
        if (res.ok) {
            const data = await res.json();
            if (data.total_goals) {
                document.getElementById('stat-goals').innerText = data.total_goals.toLocaleString() + "+";
            }
            if (data.total_users) {
                document.getElementById('stat-servers').innerText = data.total_users.toLocaleString() + "+";
            }
        }
    } catch (err) {
        // Silent fallback to default mock numbers
    }
}
