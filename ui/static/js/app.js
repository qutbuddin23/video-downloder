/**
 * Universal Video Downloader - Modern Android Material 3 Frontend Logic
 * Features: Deep stream sniffer, one-click auto download, encrypted vault,
 * in-app video preview, robust thumbnail proxy, and back navigation.
 */

let currentAnalysis = null;
let selectedFormat = null;
let currentTab = 'home';
let downloadFilter = 'all';
let pollInterval = null;
let enteredPin = '';
let isPinSetupMode = false;
let navigationHistory = ['home'];

let detectedVideoUrl = null;
let lastDetectedVideoUrl = null;
let overlayPollInterval = null;
let isCheckingClipboard = false;
const VIDEO_URL_REGEX = /(https?:\/\/[^\s]+(?:youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch|twitter\.com|x\.com|vimeo\.com|dailymotion\.com|reddit\.com|[^\s]+\.(?:mp4|m3u8|webm|mpd|mov)))/i;

const DEFAULT_VIDEO_THUMB = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 24 24" fill="%236366F1"><path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm0 2v12h16V6H4zm6 2.5l6 3.5-6 3.5v-7z"/></svg>';

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initUrlAnalyzer();
    initDownloads();
    initVault();
    initSettings();
    initBrowser();
    initClipboardDetection();
    startDownloadPolling();
    startOverlayPolling();
    loadStorageStats();
});

// --- Toast Notifications ---
function showToast(message, duration = 3500) {
    const toast = document.getElementById('toast-message');
    if (!toast) return;
    toast.textContent = message;
    toast.style.display = 'flex';
    setTimeout(() => {
        toast.style.display = 'none';
    }, duration);
}

// --- Navigation & Back Button ---
function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetTab = item.dataset.tab;
            switchTab(targetTab);
        });
    });
}

function switchTab(tabId, pushHistory = true) {
    currentTab = tabId;
    if (pushHistory) {
        if (navigationHistory[navigationHistory.length - 1] !== tabId) {
            navigationHistory.push(tabId);
        }
    }

    // Update Back button visibility in Top Bar
    const backBtn = document.getElementById('btn-top-back');
    if (backBtn) {
        backBtn.style.display = (tabId !== 'home' || navigationHistory.length > 1) ? 'inline-block' : 'none';
    }

    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    document.querySelectorAll('.screen').forEach(screen => {
        screen.classList.toggle('active', screen.id === `screen-${tabId}`);
    });

    if (tabId === 'downloads') {
        loadDownloads();
    } else if (tabId === 'vault') {
        checkVaultStatus();
    } else if (tabId === 'settings') {
        loadSettings();
        loadStorageStats();
    }
}

function appGoBack() {
    // 1. Close video player modal if open
    const playerModal = document.getElementById('player-modal');
    if (playerModal && playerModal.classList.contains('active')) {
        closePlayer();
        return;
    }

    // 2. Hide video preview card if visible on Home screen
    const previewCard = document.getElementById('video-preview-card');
    if (currentTab === 'home' && previewCard && previewCard.style.display !== 'none') {
        previewCard.style.display = 'none';
        return;
    }

    // 3. Step back in navigation history
    if (navigationHistory.length > 1) {
        navigationHistory.pop();
        const prevTab = navigationHistory[navigationHistory.length - 1];
        switchTab(prevTab, false);
    } else if (currentTab !== 'home') {
        switchTab('home', false);
    }
}

// Bridge for Android Hardware Back Button
window.onAndroidBackPressed = function() {
    appGoBack();
    return true;
};

// --- Thumbnail Proxy & Fallback Handler ---
function handleThumbnailError(img) {
    const orig = img.dataset.origSrc || img.src;
    if (orig && !img.dataset.proxied && !orig.startsWith('data:') && !orig.includes('/api/thumbnail-proxy')) {
        img.dataset.proxied = 'true';
        img.src = '/api/thumbnail-proxy?url=' + encodeURIComponent(orig);
    } else {
        img.src = DEFAULT_VIDEO_THUMB;
    }
}

function getSafeThumbnailUrl(url) {
    if (!url) return DEFAULT_VIDEO_THUMB;
    return `/api/thumbnail-proxy?url=${encodeURIComponent(url)}`;
}

// --- URL Analysis & Detection ---
function initUrlAnalyzer() {
    const pasteBtn = document.getElementById('btn-paste');
    const analyzeBtn = document.getElementById('btn-analyze');
    const urlInput = document.getElementById('url-input');
    const downloadBtn = document.getElementById('btn-start-download');

    pasteBtn.addEventListener('click', async () => {
        let text = '';
        // 1. Try web clipboard API
        if (navigator.clipboard && navigator.clipboard.readText) {
            try {
                text = await navigator.clipboard.readText();
            } catch (_) {}
        }
        // 2. Fall back to backend native Android system clipboard
        if (!text) {
            try {
                const res = await fetch('/api/clipboard/detect');
                if (res.ok) {
                    const data = await res.json();
                    text = data.url || data.raw_text;
                }
            } catch (_) {}
        }
        if (text && text.trim()) {
            urlInput.value = text.trim();
            showToast('📋 Link pasted from clipboard!');
            triggerAnalyze(text.trim());
        } else {
            showToast('Clipboard is empty. Copy a video link first!');
        }
    });

    analyzeBtn.addEventListener('click', () => {
        const url = urlInput.value.trim();
        if (url) {
            triggerAnalyze(url);
        }
    });

    downloadBtn.addEventListener('click', () => {
        if (!currentAnalysis || !selectedFormat) return;
        startDownload(currentAnalysis, selectedFormat);
    });
}

async function triggerAnalyze(url) {
    const statusText = document.getElementById('analysis-status');
    const previewCard = document.getElementById('video-preview-card');
    const drmCard = document.getElementById('drm-card');

    previewCard.style.display = 'none';
    drmCard.style.display = 'none';
    statusText.style.display = 'block';
    statusText.textContent = 'Analyzing URL & Sniffing Media Streams...';

    try {
        const res = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        const data = await res.json();
        statusText.style.display = 'none';

        if (!data.success && data.is_protected) {
            drmCard.style.display = 'block';
            document.getElementById('drm-reason').textContent = data.protection_reason || 'Protected Content';
            return;
        }

        if (!data.success) {
            alert(data.error_message || 'No downloadable streams detected on this page.');
            return;
        }

        currentAnalysis = data;
        renderVideoPreview(data);
    } catch (err) {
        statusText.style.display = 'none';
        alert('Network or server error while analyzing URL.');
    }
}

function renderVideoPreview(data) {
    const previewCard = document.getElementById('video-preview-card');
    const thumb = document.getElementById('preview-thumbnail');
    const title = document.getElementById('preview-title');
    const meta = document.getElementById('preview-meta');
    const formatsContainer = document.getElementById('formats-list');

    thumb.dataset.origSrc = data.thumbnail || '';
    thumb.dataset.proxied = '';
    thumb.src = getSafeThumbnailUrl(data.thumbnail);
    title.textContent = data.title;
    meta.textContent = `Duration: ${data.duration_str} • ${data.detected_count} Streams Found`;

    formatsContainer.innerHTML = '';
    selectedFormat = data.formats[0] || null;

    data.formats.forEach((fmt, index) => {
        const item = document.createElement('div');
        item.className = `format-item ${index === 0 ? 'selected' : ''}`;
        item.innerHTML = `
            <div>
                <div class="format-label">${fmt.quality_label} (${fmt.ext.toUpperCase()})</div>
                <div class="format-info">${fmt.codec || 'auto'} • ${fmt.filesize_str}</div>
            </div>
            <div style="font-size: 11px; font-weight: bold; color: #818CF8;">
                ${fmt.has_audio && fmt.has_video ? '✓ Video + Audio' : (fmt.has_audio ? 'Audio Only' : 'Video')}
            </div>
        `;
        item.addEventListener('click', () => {
            document.querySelectorAll('.format-item').forEach(el => el.classList.remove('selected'));
            item.classList.add('selected');
            selectedFormat = fmt;
        });
        formatsContainer.appendChild(item);
    });

    previewCard.style.display = 'block';

    // Show Back button when preview card is open
    const backBtn = document.getElementById('btn-top-back');
    if (backBtn) backBtn.style.display = 'inline-block';
}

// Watch Video Directly In-App Without Opening Website
function watchAnalyzedVideo() {
    if (!currentAnalysis) return;
    let streamUrl = currentAnalysis.direct_url;
    if (!streamUrl && selectedFormat && selectedFormat.direct_url) {
        streamUrl = selectedFormat.direct_url;
    }
    if (!streamUrl && currentAnalysis.formats && currentAnalysis.formats.length > 0) {
        streamUrl = currentAnalysis.formats[0].direct_url;
    }

    if (streamUrl) {
        const modal = document.getElementById('player-modal');
        const player = document.getElementById('media-player');
        const extBtn = document.getElementById('btn-player-open-external');
        const errBox = document.getElementById('player-error-msg');
        if (errBox) errBox.style.display = 'none';
        if (extBtn) extBtn.style.display = 'none';

        // Route through local stream proxy to prevent 403 Forbidden on mobile
        player.onerror = () => {
            if (errBox) {
                errBox.style.display = 'block';
                errBox.innerHTML = `
                    <div style="margin-bottom:8px;">⚠️ WebView video player could not stream this video directly.</div>
                    <button class="btn btn-primary btn-sm" onclick="startDownload(currentAnalysis, selectedFormat || currentAnalysis.formats[0])" style="font-size:12px;">⬇ Download to Phone to Watch Offline</button>
                `;
            }
        };

        player.src = `/api/stream-proxy?url=${encodeURIComponent(streamUrl)}`;
        modal.classList.add('active');
        player.play().catch(e => console.log('Autoplay deferred:', e));
    } else {
        showToast('⚡ Starting download so you can watch in HD player!');
        startDownload(currentAnalysis, selectedFormat || currentAnalysis.formats[0]);
    }
}

async function startDownload(analysis, fmt) {
    try {
        const res = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: analysis.source_url,
                title: analysis.title,
                quality_label: fmt.quality_label,
                format_selector: fmt.download_selector,
                direct_url: fmt.direct_url,
                thumbnail: analysis.thumbnail,
                duration: analysis.duration
            })
        });
        const result = await res.json();
        if (result.success) {
            showToast(`⬇ Download started: ${analysis.title}`);
            switchTab('downloads');
        }
    } catch (err) {
        alert('Failed to start download.');
    }
}

// --- Downloads List & Management ---
function initDownloads() {
    document.querySelectorAll('.segment-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.segment-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            downloadFilter = btn.dataset.filter;
            loadDownloads();
        });
    });
}

function startDownloadPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(() => {
        if (currentTab === 'downloads') {
            loadDownloads(false);
        }
    }, 2000);
}

let lastRenderedDownloadIds = '';

async function loadDownloads(showLoading = true) {
    try {
        const res = await fetch(`/api/downloads?filter=${downloadFilter}`);
        const items = await res.json();
        
        // Update downloads count badges
        const totalCount = items ? items.length : 0;
        const activeCount = items ? items.filter(it => it.status === 'downloading' || it.status === 'queued').length : 0;
        
        const summaryCountEl = document.getElementById('dl-summary-count');
        if (summaryCountEl) summaryCountEl.textContent = totalCount;
        
        const activeBadgeEl = document.getElementById('dl-active-count-badge');
        if (activeBadgeEl) {
            activeBadgeEl.textContent = activeCount > 0 ? `⚡ ${activeCount} Downloading` : '0 Active';
            activeBadgeEl.style.color = activeCount > 0 ? '#10B981' : '#94A3B8';
        }

        const navBadgeEl = document.getElementById('nav-downloads-count');
        if (navBadgeEl) {
            if (activeCount > 0) {
                navBadgeEl.textContent = activeCount;
                navBadgeEl.style.display = 'inline-block';
            } else {
                navBadgeEl.style.display = 'none';
            }
        }

        renderDownloadsList(items);
    } catch (err) {
        console.error('Error fetching downloads:', err);
    }
}

function renderDownloadsList(items) {
    const list = document.getElementById('downloads-list');
    if (!items || items.length === 0) {
        lastRenderedDownloadIds = '';
        list.innerHTML = `<div style="text-align:center; padding: 40px 10px; color: #94A3B8;">No downloads found in this tab.</div>`;
        return;
    }

    // Check if item structure changed (e.g. items added, removed, or changed status)
    const currentSignature = items.map(it => `${it.id}:${it.status}`).join('|');
    if (currentSignature === lastRenderedDownloadIds) {
        // Fast path: smoothly update progress numbers and bars without destroying DOM elements
        items.forEach(item => {
            const fill = document.getElementById(`prog-fill-${item.id}`);
            if (fill) fill.style.width = `${item.progress}%`;
            const pct = document.getElementById(`prog-pct-${item.id}`);
            if (pct) pct.textContent = `${item.progress.toFixed(1)}%`;
            const mb = document.getElementById(`prog-mb-${item.id}`);
            if (mb) mb.textContent = `${((item.downloaded_bytes || 0) / (1024*1024)).toFixed(1)} MB`;
            const meta = document.getElementById(`meta-info-${item.id}`);
            if (meta) {
                let speedText = (item.status === 'downloading' && item.speed > 0)
                    ? ` • ${(item.speed / (1024 * 1024)).toFixed(2)} MB/s` : '';
                meta.innerHTML = `${item.quality} • Status: <b style="color:#818CF8">${item.status.toUpperCase()}</b>${speedText}`;
            }
        });
        return;
    }

    lastRenderedDownloadIds = currentSignature;

    list.innerHTML = items.map(item => {
        const isDownloading = item.status === 'downloading';
        const isPaused = item.status === 'paused';
        const isCompleted = item.status === 'completed';

        let speedText = '';
        if (isDownloading && item.speed > 0) {
            speedText = ` • ${(item.speed / (1024 * 1024)).toFixed(2)} MB/s`;
        }

        const thumbSrc = getSafeThumbnailUrl(item.thumbnail);

        return `
            <div class="download-item" id="dl-card-${item.id}">
                <div class="dl-header">
                    <img class="dl-thumb" src="${thumbSrc}" referrerpolicy="no-referrer" onerror="handleThumbnailError(this)" data-orig-src="${item.thumbnail || ''}" />
                    <div class="dl-info">
                        <div class="dl-title">${item.title}</div>
                        <div class="dl-meta" id="meta-info-${item.id}">${item.quality} • Status: <b style="color:#818CF8">${item.status.toUpperCase()}</b>${speedText}</div>
                    </div>
                </div>
                ${!isCompleted ? `
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill" id="prog-fill-${item.id}" style="width: ${item.progress}%"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:11px; color:#94A3B8;">
                        <span id="prog-pct-${item.id}">${item.progress.toFixed(1)}%</span>
                        <span id="prog-mb-${item.id}">${((item.downloaded_bytes || 0) / (1024*1024)).toFixed(1)} MB</span>
                    </div>
                ` : ''}
                <div class="dl-actions">
                    ${isDownloading ? `<button class="btn btn-secondary btn-sm" onclick="pauseDownload('${item.id}')">⏸ Pause</button>` : ''}
                    ${isPaused ? `<button class="btn btn-primary btn-sm" onclick="resumeDownload('${item.id}')">▶ Resume</button>` : ''}
                    ${!isCompleted ? `<button class="btn btn-danger btn-sm" onclick="cancelDownload('${item.id}')">✕ Cancel</button>` : ''}
                    ${isCompleted ? `
                        <button class="btn btn-primary btn-sm" onclick="playVideo('${item.id}')">▶ Play</button>
                        <button class="btn btn-secondary btn-sm" onclick="openInPhonePlayer('${item.id}')" title="Open in phone gallery or video player">📱 Open</button>
                        <button class="btn btn-secondary btn-sm" onclick="hideInVault('${item.id}')">🔒 Hide in Vault</button>
                        <button class="btn btn-danger btn-sm" onclick="deleteDownload('${item.id}')">🗑 Delete</button>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');
}

async function pauseDownload(id) {
    await fetch(`/api/downloads/${id}/pause`, { method: 'POST' });
    loadDownloads();
}

async function resumeDownload(id) {
    await fetch(`/api/downloads/${id}/resume`, { method: 'POST' });
    loadDownloads();
}

async function cancelDownload(id) {
    await fetch(`/api/downloads/${id}/cancel`, { method: 'POST' });
    loadDownloads();
}

async function deleteDownload(id) {
    if (confirm('Delete this download and file?')) {
        await fetch(`/api/downloads/${id}`, { method: 'DELETE' });
        loadDownloads();
        loadStorageStats();
    }
}

async function hideInVault(id) {
    try {
        let res = await fetch('/api/vault/hide', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ download_id: id })
        });
        let result = await res.json();

        if (!result.success && res.status === 403) {
            const pin = prompt('Private Vault is locked. Enter Master PIN:');
            if (pin) {
                const unlockRes = await fetch('/api/vault/unlock', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pin: pin.trim() })
                });
                const unlockData = await unlockRes.json();
                if (unlockData.success) {
                    res = await fetch('/api/vault/hide', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ download_id: id })
                    });
                    result = await res.json();
                } else {
                    alert('Incorrect PIN. Video remains in downloads.');
                    return;
                }
            } else {
                return;
            }
        }

        if (result.success) {
            showToast('🔒 Video encrypted and moved into Private Vault!');
            loadDownloads();
            loadStorageStats();
        } else {
            alert(result.detail || result.error || 'Failed to hide video.');
        }
    } catch (err) {
        alert('Vault error: ' + err.message);
    }
}

// --- Private Vault (Secret PIN, No Plaintext Disclosure) ---
function initVault() {
    document.querySelectorAll('.keypad-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const digit = btn.dataset.num;
            if (digit === 'C') {
                enteredPin = '';
            } else if (digit === 'OK') {
                submitPin();
            } else if (enteredPin.length < 6) {
                enteredPin += digit;
                if (enteredPin.length === 4) {
                    submitPin();
                }
            }
            updatePinDots();
        });
    });

    const lockBtn = document.getElementById('btn-lock-vault');
    if (lockBtn) {
        lockBtn.addEventListener('click', async () => {
            await fetch('/api/vault/lock', { method: 'POST' });
            checkVaultStatus();
        });
    }
}

function updatePinDots() {
    for (let i = 1; i <= 4; i++) {
        const dot = document.getElementById(`pin-dot-${i}`);
        if (dot) {
            dot.classList.toggle('filled', enteredPin.length >= i);
        }
    }
}

async function checkVaultStatus() {
    try {
        const res = await fetch('/api/vault/status');
        const stats = await res.json();

        const lockedView = document.getElementById('vault-locked-view');
        const unlockedView = document.getElementById('vault-unlocked-view');
        const pinTitle = document.getElementById('vault-pin-title');

        if (!stats.is_pin_set) {
            isPinSetupMode = true;
            pinTitle.textContent = 'Set Your 4-Digit Master PIN';
            lockedView.style.display = 'block';
            unlockedView.style.display = 'none';
        } else if (!stats.is_unlocked) {
            isPinSetupMode = false;
            // Secret PIN - never print password in UI text!
            pinTitle.textContent = 'Enter Vault PIN';
            lockedView.style.display = 'block';
            unlockedView.style.display = 'none';
        } else {
            lockedView.style.display = 'none';
            unlockedView.style.display = 'block';
            loadVaultItems(stats);
        }
    } catch (err) {
        console.error('Error checking vault:', err);
    }
}

function startOverlayPolling() {
    setInterval(async () => {
        try {
            const res = await fetch('/api/overlay/latest-url');
            const data = await res.json();
            if (data && data.url) {
                if (data.auto_downloaded) {
                    showToast(`⚡ Auto-Downloading: ${data.title || 'Video'}`);
                    switchTab('downloads');
                    loadDownloads();
                } else {
                    switchTab('home');
                    const urlInput = document.getElementById('url-input');
                    if (urlInput) {
                        urlInput.value = data.url;
                        triggerAnalyze(data.url);
                    }
                }
            }
        } catch (e) {
            // Ignore polling errors
        }
    }, 1500);
}

async function submitPin() {
    if (!enteredPin) return;
    const pin = enteredPin;
    enteredPin = '';
    updatePinDots();

    const endpoint = isPinSetupMode ? '/api/vault/set-pin' : '/api/vault/unlock';
    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pin })
        });
        const data = await res.json();
        if (data.success) {
            checkVaultStatus();
            loadStorageStats();
        } else {
            alert('Incorrect PIN.');
        }
    } catch (err) {
        alert('Authentication error.');
    }
}

async function loadVaultItems(stats) {
    document.getElementById('vault-stats-weight').textContent = `${stats.total_size_str} (${stats.total_count} Videos)`;
    try {
        const res = await fetch('/api/vault/items');
        const items = await res.json();
        const list = document.getElementById('vault-items-list');

        if (!items || items.length === 0) {
            list.innerHTML = `<div style="text-align:center; padding: 40px; color:#94A3B8;">Your Private Vault is empty.<br>Hide videos from the Downloads screen.</div>`;
            return;
        }

        list.innerHTML = items.map(item => {
            const thumbSrc = getSafeThumbnailUrl(item.thumbnail);
            return `
                <div class="download-item" style="border-left: 3px solid #EC4899;">
                    <div class="dl-header">
                        <img class="dl-thumb" src="${thumbSrc}" referrerpolicy="no-referrer" onerror="handleThumbnailError(this)" data-orig-src="${item.thumbnail || ''}" />
                        <div class="dl-info">
                            <div class="dl-title">🔒 ${item.title}</div>
                            <div class="dl-meta">${item.file_size_str} • Encrypted AES-256</div>
                        </div>
                    </div>
                    <div class="dl-actions">
                        <button class="btn btn-primary btn-sm" onclick="playVaultVideo('${item.id}')">▶ Secure Play</button>
                        <button class="btn btn-secondary btn-sm" onclick="restoreVaultVideo('${item.id}')">Restore</button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error('Error fetching vault items:', err);
    }
}

async function restoreVaultVideo(id) {
    try {
        const res = await fetch(`/api/vault/restore/${id}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast('Video restored to public Downloads!');
            checkVaultStatus();
            loadStorageStats();
        }
    } catch (err) {
        alert('Restore error.');
    }
}

let currentPlayingDownloadId = null;

// --- Video Player Modal & Phone Player Launcher ---
function playVideo(downloadId) {
    currentPlayingDownloadId = downloadId;
    const modal = document.getElementById('player-modal');
    const player = document.getElementById('media-player');
    const extBtn = document.getElementById('btn-player-open-external');
    const errBox = document.getElementById('player-error-msg');
    if (errBox) errBox.style.display = 'none';
    if (extBtn) extBtn.style.display = 'inline-block';

    player.onerror = () => {
        if (errBox) {
            errBox.style.display = 'block';
            errBox.innerHTML = `
                <div style="margin-bottom:8px;">⚠️ Built-in WebView cannot decode this video container/codec.</div>
                <button class="btn btn-primary btn-sm" onclick="openCurrentInExternalPlayer()" style="font-size:12px;">📱 Play in Phone Video Player (VLC / MX / Gallery)</button>
            `;
        }
    };

    player.src = `/media/stream/${downloadId}`;
    modal.classList.add('active');
    player.play().catch(e => console.log('Autoplay deferred:', e));
}

async function openCurrentInExternalPlayer() {
    if (currentPlayingDownloadId) {
        await openInPhonePlayer(currentPlayingDownloadId);
    }
}

async function openInPhonePlayer(downloadId) {
    try {
        showToast('📱 Opening video in your phone player / gallery...');
        const res = await fetch(`/api/downloads/${downloadId}/open`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast('✅ Opened in phone video player!');
        } else {
            showToast('Playing in built-in HD player...');
            playVideo(downloadId);
        }
    } catch (err) {
        console.error('Error opening external player:', err);
        playVideo(downloadId);
    }
}

async function playVaultVideo(vaultId) {
    try {
        const res = await fetch(`/api/vault/play/${vaultId}`);
        const data = await res.json();
        if (data.stream_url) {
            const modal = document.getElementById('player-modal');
            const player = document.getElementById('media-player');
            const errBox = document.getElementById('player-error-msg');
            if (errBox) errBox.style.display = 'none';
            player.src = data.stream_url;
            modal.classList.add('active');
            player.play().catch(e => console.log('Autoplay deferred:', e));
        }
    } catch (err) {
        alert('Failed to stream private video.');
    }
}

function closePlayer() {
    const modal = document.getElementById('player-modal');
    const player = document.getElementById('media-player');
    const errBox = document.getElementById('player-error-msg');
    if (errBox) errBox.style.display = 'none';
    player.pause();
    player.removeAttribute('src');
    player.load();
    modal.classList.remove('active');
}

// --- Storage & Settings ---
async function loadStorageStats() {
    try {
        const res = await fetch('/api/storage/stats');
        const stats = await res.json();

        document.getElementById('storage-downloads-text').textContent = stats.downloads_size_str;
        document.getElementById('storage-vault-text').textContent = stats.vault_size_str;
        document.getElementById('storage-free-text').textContent = stats.free_disk_str;

        document.getElementById('meter-downloads').style.width = `${Math.min(100, stats.downloads_percent * 2)}%`;
        document.getElementById('meter-vault').style.width = `${Math.min(100, stats.vault_percent * 2)}%`;
        document.getElementById('meter-free').style.width = `${Math.max(10, 100 - (stats.downloads_percent + stats.vault_percent)*2)}%`;

        const tempBadge = document.getElementById('temp-files-badge');
        if (tempBadge) tempBadge.textContent = `${stats.temp_size_str} (${stats.temp_count} files)`;
    } catch (err) {
        console.error('Error fetching storage stats:', err);
    }
}

async function cleanTempFiles() {
    try {
        const res = await fetch('/api/storage/clean-temp', { method: 'POST' });
        const data = await res.json();
        showToast(`Cleaned ${data.freed_str} of temporary files.`);
        loadStorageStats();
    } catch (err) {
        alert('Error cleaning files.');
    }
}

// --- Settings & Floating Button Controls ---
async function initSettings() {
    const overlayToggle = document.getElementById('toggle-floating-button');
    if (overlayToggle) {
        overlayToggle.addEventListener('change', async () => {
            const isChecked = overlayToggle.checked;
            try {
                await fetch('/api/overlay/toggle', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: isChecked })
                });
                if (isChecked) {
                    await checkOverlayPermissionStatus();
                }
            } catch (err) {
                console.error('Toggle overlay error:', err);
            }
        });
    }
}

async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        const settings = await res.json();
        const toggle = document.getElementById('toggle-floating-button');
        if (toggle && settings.floating_button_enabled !== undefined) {
            toggle.checked = settings.floating_button_enabled === 'true';
        }
        await checkOverlayPermissionStatus();
    } catch (err) {
        console.error('Error loading settings:', err);
    }
}

async function checkOverlayPermissionStatus() {
    try {
        const res = await fetch('/api/overlay/status');
        if (!res.ok) return;
        const data = await res.json();
        const permBox = document.getElementById('overlay-permission-box');
        const statusDesc = document.getElementById('overlay-status-desc');
        const toggle = document.getElementById('toggle-floating-button');

        if (toggle && typeof data.enabled === 'boolean') {
            toggle.checked = data.enabled;
        }

        if (data.is_android) {
            if (!data.can_draw) {
                if (permBox) permBox.style.display = 'block';
                if (statusDesc) {
                    statusDesc.textContent = '⚠️ Tap below to enable "Appear on top"';
                    statusDesc.style.color = '#F59E0B';
                }
            } else {
                if (permBox) permBox.style.display = 'none';
                if (statusDesc) {
                    statusDesc.textContent = '✅ Active: Draws floating button over other apps';
                    statusDesc.style.color = '#10B981';
                }
            }
        } else {
            if (permBox) permBox.style.display = 'none';
            if (statusDesc) {
                statusDesc.textContent = 'Always-On-Top floating bubble assistant';
                statusDesc.style.color = '#94A3B8';
            }
        }
    } catch (err) {
        console.error('Overlay status check error:', err);
    }
}

async function requestOverlayPermission() {
    showToast('Opening Android Settings... Please enable "Allow display over other apps".', 5000);
    try {
        await fetch('/api/overlay/request-permission', { method: 'POST' });
    } catch (err) {
        console.error('Request permission error:', err);
    }
}

// --- Zero-Paste Video Auto-Detection & Clipboard Monitoring ---
function initClipboardDetection() {
    // Check when window gains focus or switches to foreground
    window.addEventListener('focus', () => {
        checkClipboardForVideo();
        checkOverlayPermissionStatus();
    });

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            checkClipboardForVideo();
            checkOverlayPermissionStatus();
        }
    });

    // Initial check after page renders
    setTimeout(checkClipboardForVideo, 600);

    // Continuous poll every 4.0s for background copy detection
    setInterval(checkClipboardForVideo, 4000);
}

async function checkClipboardForVideo() {
    if (isCheckingClipboard) return;
    isCheckingClipboard = true;

    try {
        let foundUrl = null;

        // Method 1: Web Clipboard API (Browser / WebView)
        if (navigator.clipboard && navigator.clipboard.readText) {
            try {
                const text = await navigator.clipboard.readText();
                if (text) {
                    const match = text.match(VIDEO_URL_REGEX);
                    if (match) {
                        foundUrl = match[1];
                    }
                }
            } catch (_) {
                // Clipboard read permission might require user interaction or prompt
            }
        }

        // Method 2: Android Native System Clipboard via PyJNIus
        if (!foundUrl) {
            try {
                const res = await fetch('/api/clipboard/detect');
                if (res.ok) {
                    const data = await res.json();
                    if (data.has_video && data.url) {
                        foundUrl = data.url;
                    }
                }
            } catch (_) {}
        }

        if (foundUrl && foundUrl !== lastDetectedVideoUrl) {
            handleVideoDetected(foundUrl);
        }
    } finally {
        isCheckingClipboard = false;
    }
}

function handleVideoDetected(url) {
    if (!url) return;
    detectedVideoUrl = url;
    lastDetectedVideoUrl = url;

    // 1. Show Auto-Detect Card on Home Screen
    const card = document.getElementById('auto-detect-card');
    const preview = document.getElementById('auto-detect-url-preview');
    if (card && preview) {
        preview.textContent = url;
        card.style.display = 'block';
    }

    // 2. Pulse Floating Action Button with green glow & badge
    const fab = document.getElementById('fab-auto-download');
    const badge = document.getElementById('fab-badge');
    if (fab) {
        fab.classList.add('has-detected');
    }
    if (badge) {
        badge.style.display = 'flex';
    }

    // 3. Pre-fill URL input if currently empty
    const urlInput = document.getElementById('url-input');
    if (urlInput && !urlInput.value.trim()) {
        urlInput.value = url;
    }
}

// 1-Click Auto Download Handler (from card)
function quickAutoDownloadDetected() {
    if (detectedVideoUrl) {
        quickAutoDownloadUrl(detectedVideoUrl);
    } else {
        const urlInput = document.getElementById('url-input');
        if (urlInput && urlInput.value.trim()) {
            quickAutoDownloadUrl(urlInput.value.trim());
        }
    }
}

// 1-Click Auto Download Handler (from floating action button)
async function onFabClicked() {
    if (detectedVideoUrl) {
        quickAutoDownloadUrl(detectedVideoUrl);
        return;
    }

    showToast('🔍 Checking clipboard for video link...');
    await checkClipboardForVideo();

    if (detectedVideoUrl) {
        quickAutoDownloadUrl(detectedVideoUrl);
        return;
    }

    const urlInput = document.getElementById('url-input');
    if (urlInput && urlInput.value.trim()) {
        quickAutoDownloadUrl(urlInput.value.trim());
        return;
    }

    showToast('📋 Copy a video link in any app, then tap ⚡ to download!');
}

async function quickAutoDownloadUrl(url) {
    if (!url) return;
    showToast('⚡ Auto-Detecting video & starting download...', 3500);

    // Hide auto-detect card and remove pulse state
    const card = document.getElementById('auto-detect-card');
    if (card) card.style.display = 'none';
    const fab = document.getElementById('fab-auto-download');
    if (fab) fab.classList.remove('has-detected');
    const badge = document.getElementById('fab-badge');
    if (badge) badge.style.display = 'none';

    detectedVideoUrl = null;

    try {
        const res = await fetch('/api/auto-download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`🚀 Auto-Downloading: ${data.title || 'Video'}`, 4000);
            switchTab('downloads');
            loadDownloads();
        } else {
            showToast('Sniffing page media streams...');
            switchTab('home');
            const urlInput = document.getElementById('url-input');
            if (urlInput) urlInput.value = url;
            triggerAnalyze(url);
        }
    } catch (err) {
        showToast('Auto-download request failed.');
        console.error(err);
    }
}

// Polling for overlay events triggered outside the app (native overlay bubble)
function startOverlayPolling() {
    if (overlayPollInterval) clearInterval(overlayPollInterval);
    overlayPollInterval = setInterval(async () => {
        try {
            const res = await fetch('/api/overlay/latest-url');
            if (!res.ok) return;
            const data = await res.json();
            if (data.url) {
                if (data.auto_downloaded) {
                    showToast(`⚡ Background Auto-Download: ${data.title || 'Video'}`, 4000);
                    if (currentTab === 'downloads') {
                        loadDownloads();
                    }
                } else {
                    handleVideoDetected(data.url);
                }
            }
        } catch (_) {}
    }, 3000);
}

// Launch floating bubble onto screen
async function showFloatingBubble() {
    showToast('🚀 Bringing Floating Bubble onto screen...', 3000);
    try {
        const res = await fetch('/api/overlay/show', { method: 'POST' });
        const data = await res.json();
        if (data.message) {
            showToast(data.message, 5000);
        }
        await checkOverlayPermissionStatus();
    } catch (err) {
        showToast('Failed to start floating bubble.');
    }
}

// Export functions to window for HTML onclick attributes
window.quickAutoDownloadDetected = quickAutoDownloadDetected;
window.onFabClicked = onFabClicked;
window.requestOverlayPermission = requestOverlayPermission;
window.showFloatingBubble = showFloatingBubble;
window.openInPhonePlayer = openInPhonePlayer;
window.openCurrentInExternalPlayer = openCurrentInExternalPlayer;
window.appGoBack = appGoBack;

// --- In-App Browser ---
function initBrowser() {
    const goBtn = document.getElementById('btn-browser-go');
    const input = document.getElementById('browser-url-input');
    const iframe = document.getElementById('browser-webview');
    const detectBtn = document.getElementById('btn-browser-detect');

    if (goBtn && input && iframe) {
        goBtn.addEventListener('click', () => {
            let url = input.value.trim();
            if (url && !url.startsWith('http://') && !url.startsWith('https://')) {
                url = 'https://' + url;
            }
            iframe.src = url;
        });

        detectBtn.addEventListener('click', () => {
            const url = input.value.trim();
            if (url) {
                switchTab('home');
                document.getElementById('url-input').value = url;
                triggerAnalyze(url);
            }
        });
    }
}
