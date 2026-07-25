/* ═══════════════════════════════════════════════════════════════
   Jingle Creator — Frontend Logic
   ═══════════════════════════════════════════════════════════════ */

'use strict';

// ─── State ────────────────────────────────────────────────────
const state = {
  videoUrl: '',
  duration: 0,       // seconds (float)
  startSec: 0,
  endSec: 0,
  fadeIn: 0,
  fadeOut: 0,
  isLoading: false,
};

// ─── DOM References ───────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const els = {
  urlInput:       $('yt-url'),
  loadBtn:        $('load-btn'),
  videoInfoCard:  $('video-info-card'),
  videoThumb:     $('video-thumb'),
  videoTitle:     $('video-title'),
  videoUploader:  $('video-uploader'),
  videoDuration:  $('video-duration-display'),
  trimCard:       $('trim-card'),
  startHandle:    $('start-handle'),
  endHandle:      $('end-handle'),
  timelineFill:   $('timeline-fill'),
  startTimeDisp:  $('start-time-display'),
  endTimeDisp:    $('end-time-display'),
  selectedDur:    $('selected-duration'),
  timelineTicks:  $('timeline-ticks'),
  fadesCard:      $('fades-card'),
  fadeInSlider:   $('fade-in-slider'),
  fadeOutSlider:  $('fade-out-slider'),
  fadeInValue:    $('fade-in-value'),
  fadeOutValue:   $('fade-out-value'),
  outputCard:     $('output-card'),
  filenameInput:  $('filename-input'),
  previewBtn:     $('preview-btn'),
  downloadBtn:    $('download-btn'),
  audioSection:   $('audio-player-section'),
  audioPlayer:    $('audio-player'),
  loadingOverlay: $('loading-overlay'),
  loadingMsg:     $('loading-msg'),
  toastContainer: $('toast-container'),
};

// ─── Time Formatting ──────────────────────────────────────────
function formatTime(seconds) {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(1).padStart(4, '0')}`;
}

function formatDuration(seconds) {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  if (m === 0) return `${sec}s`;
  return `${m}m ${sec}s`;
}

// ─── Loading Overlay ──────────────────────────────────────────
function showLoading(msg = 'Loading…') {
  els.loadingMsg.textContent = msg;
  els.loadingOverlay.classList.add('visible');
  state.isLoading = true;
}

function hideLoading() {
  els.loadingOverlay.classList.remove('visible');
  state.isLoading = false;
}

// ─── Toast Notifications ──────────────────────────────────────
function showToast(message, type = 'success', duration = 3500) {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const icon = type === 'error' ? '✕' : type === 'success' ? '✓' : 'ℹ';
  toast.innerHTML = `<span class="toast-icon">${icon}</span><span>${message}</span>`;
  els.toastContainer.appendChild(toast);

  requestAnimationFrame(() => {
    requestAnimationFrame(() => toast.classList.add('show'));
  });

  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 400);
  }, duration);
}

// ─── Timeline Ticks ───────────────────────────────────────────
function buildTicks() {
  const dur = state.duration;
  if (!dur) return;

  // Pick a sensible tick interval
  let interval = 5;
  if (dur > 300) interval = 60;
  else if (dur > 120) interval = 30;
  else if (dur > 60) interval = 15;
  else if (dur > 30) interval = 10;

  const ticks = [];
  for (let t = 0; t <= dur; t += interval) {
    const pct = (t / dur) * 100;
    ticks.push(`<span class="tick" style="position:absolute;left:${pct}%;transform:translateX(-50%)">${formatTime(t)}</span>`);
  }
  // Always show end
  const endLabel = formatTime(dur);
  if (!ticks.find(t => t.includes(endLabel))) {
    ticks.push(`<span class="tick" style="position:absolute;right:0;transform:translateX(50%)">${endLabel}</span>`);
  }

  els.timelineTicks.style.position = 'relative';
  els.timelineTicks.innerHTML = ticks.join('');
}

// ─── Timeline Fill Update ─────────────────────────────────────
function updateTimelineFill() {
  const startPct = parseFloat(els.startHandle.value);
  const endPct   = parseFloat(els.endHandle.value);
  els.timelineFill.style.left  = `${startPct}%`;
  els.timelineFill.style.width = `${endPct - startPct}%`;

  state.startSec = (startPct / 100) * state.duration;
  state.endSec   = (endPct   / 100) * state.duration;

  els.startTimeDisp.textContent = formatTime(state.startSec);
  els.endTimeDisp.textContent   = formatTime(state.endSec);

  const clipDur = state.endSec - state.startSec;
  if (clipDur > 0) {
    els.selectedDur.textContent = `${formatDuration(clipDur)} selected`;
    els.selectedDur.style.color = 'var(--cyan-bright)';
  } else {
    els.selectedDur.textContent = '— select a range —';
    els.selectedDur.style.color = '';
  }
}

// ─── Dual Handle Events ───────────────────────────────────────
function onStartChange() {
  const startVal = parseFloat(els.startHandle.value);
  const endVal   = parseFloat(els.endHandle.value);
  // Enforce start < end (keep at least 1% gap)
  if (startVal >= endVal - 1) {
    els.startHandle.value = Math.max(0, endVal - 1);
  }
  updateTimelineFill();
}

function onEndChange() {
  const startVal = parseFloat(els.startHandle.value);
  const endVal   = parseFloat(els.endHandle.value);
  if (endVal <= startVal + 1) {
    els.endHandle.value = Math.min(100, startVal + 1);
  }
  updateTimelineFill();
}

// ─── Fade Display Update ──────────────────────────────────────
function updateFadeDisplay(which) {
  if (which === 'fade-in') {
    state.fadeIn = parseFloat(els.fadeInSlider.value);
    els.fadeInValue.textContent = `${state.fadeIn.toFixed(1)}s`;
  } else {
    state.fadeOut = parseFloat(els.fadeOutSlider.value);
    els.fadeOutValue.textContent = `${state.fadeOut.toFixed(1)}s`;
  }
}

// ─── Load Video ───────────────────────────────────────────────
async function loadVideo() {
  const url = els.urlInput.value.trim();
  if (!url) {
    showToast('Please enter a YouTube URL', 'error');
    els.urlInput.focus();
    return;
  }

  showLoading('Fetching video info…');
  els.loadBtn.disabled = true;

  try {
    const res = await fetch('/api/fetch-info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const info = await res.json();

    // Populate video info card
    state.videoUrl  = url;
    state.duration  = info.duration || 0;

    els.videoTitle.textContent    = info.title;
    els.videoUploader.textContent = info.uploader;
    els.videoDuration.textContent = `⏱ ${formatDuration(state.duration)}`;

    if (info.thumbnail) {
      els.videoThumb.src = info.thumbnail;
      els.videoThumb.style.display = 'block';
    } else {
      els.videoThumb.style.display = 'none';
    }

    // Set default filename from video title (sanitized)
    const safeName = info.title
      .replace(/[^a-zA-Z0-9\s_-]/g, '')
      .replace(/\s+/g, '_')
      .substring(0, 40);
    els.filenameInput.value = safeName || 'jingle';

    // Initialize range slider
    els.startHandle.value = '0';
    els.endHandle.value   = '100';
    updateTimelineFill();
    buildTicks();

    // Reset fades
    els.fadeInSlider.value = '0';
    els.fadeOutSlider.value = '0';
    updateFadeDisplay('fade-in');
    updateFadeDisplay('fade-out');

    // Hide audio player from previous session
    els.audioSection.style.display = 'none';
    if (els.audioPlayer.src) {
      URL.revokeObjectURL(els.audioPlayer.src);
      els.audioPlayer.src = '';
    }

    // Show cards
    els.videoInfoCard.style.display = 'block';
    els.trimCard.style.display = 'block';
    els.fadesCard.style.display = 'block';
    els.outputCard.style.display = 'block';

    // Scroll into trim
    setTimeout(() => els.trimCard.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
    showToast(`Loaded: ${info.title.substring(0, 40)}${info.title.length > 40 ? '…' : ''}`, 'success');

  } catch (err) {
    showToast(err.message || 'Failed to load video', 'error', 5000);
  } finally {
    hideLoading();
    els.loadBtn.disabled = false;
  }
}

// ─── Build Process Payload ────────────────────────────────────
function buildPayload() {
  const start = state.startSec;
  const end   = state.endSec;

  if (!state.videoUrl) throw new Error('No video loaded');
  if (end <= start)    throw new Error('Invalid trim range — drag the handles');
  if (end - start < 0.5) throw new Error('Clip is too short (min 0.5s)');
  if (end - start > 60)  throw new Error('Clip is too long (max 60s)');

  return {
    url:      state.videoUrl,
    start:    Math.round(start * 100) / 100,
    end:      Math.round(end   * 100) / 100,
    fade_in:  state.fadeIn,
    fade_out: state.fadeOut,
    filename: els.filenameInput.value.trim() || 'jingle',
  };
}

// ─── Fetch Processed Audio Blob ───────────────────────────────
async function fetchAudioBlob(loadingMessage) {
  const payload = buildPayload();
  showLoading(loadingMessage);
  setActionBtnsDisabled(true);

  const res = await fetch('/api/process', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Processing failed' }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }

  const blob = await res.blob();
  const filename = res.headers.get('X-Filename') || `${payload.filename}.mp3`;
  return { blob, filename };
}

function setActionBtnsDisabled(disabled) {
  els.previewBtn.disabled  = disabled;
  els.downloadBtn.disabled = disabled;
}

// ─── Preview ──────────────────────────────────────────────────
async function previewJingle() {
  try {
    const { blob } = await fetchAudioBlob('Processing preview…');

    // Revoke old blob URL
    if (els.audioPlayer.src?.startsWith('blob:')) {
      URL.revokeObjectURL(els.audioPlayer.src);
    }

    const blobUrl = URL.createObjectURL(blob);
    els.audioPlayer.src = blobUrl;
    els.audioSection.style.display = 'block';
    els.audioSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    // Autoplay
    try {
      await els.audioPlayer.play();
    } catch {
      // Autoplay blocked — that's fine, controls are visible
    }

    showToast('Preview ready — hit play! 🎧', 'success');
  } catch (err) {
    showToast(err.message || 'Preview failed', 'error', 5000);
  } finally {
    hideLoading();
    setActionBtnsDisabled(false);
  }
}

// ─── Download ─────────────────────────────────────────────────
async function downloadJingle() {
  try {
    const { blob, filename } = await fetchAudioBlob('Processing jingle…');

    const url  = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href     = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => URL.revokeObjectURL(url), 5000);

    showToast(`Downloaded: ${filename} ✓`, 'success');
  } catch (err) {
    showToast(err.message || 'Download failed', 'error', 5000);
  } finally {
    hideLoading();
    setActionBtnsDisabled(false);
  }
}

// ─── Enter Key on URL Input ───────────────────────────────────
els.urlInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') loadVideo();
});

// ─── Paste auto-load ──────────────────────────────────────────
els.urlInput.addEventListener('paste', () => {
  setTimeout(() => {
    const val = els.urlInput.value.trim();
    if (val.includes('youtube.com') || val.includes('youtu.be')) {
      loadVideo();
    }
  }, 50);
});
