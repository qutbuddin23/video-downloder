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
const VIDEO_URL_REGEX = /(https?:\/\/[^\s<>"'`]+)/i;

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
function getDefaultFileThumb(nameOrUrl = '') {
    const s = (nameOrUrl || '').toLowerCase();
    if (s.endsWith('.apk') || s.endsWith('.xapk')) {
        return 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 24 24" fill="%2310B981"><path d="M16.6 6.1l1.5-2.6a.75.75 0 1 0-1.3-.8l-1.6 2.7c-1-.4-2.1-.6-3.2-.6s-2.2.2-3.2.6L7.2 2.7a.75.75 0 0 0-1.3.8l1.5 2.6C4.4 7.6 2.5 10.7 2.1 14.5h19.8c-.4-3.8-2.3-6.9-5.3-8.4zM8 11.5a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm8 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zM3 16h18v1.5a2.5 2.5 0 0 1-2.5 2.5H5.5A2.5 2.5 0 0 1 3 17.5V16z"/></svg>';
    }
    if (s.endsWith('.zip') || s.endsWith('.rar') || s.endsWith('.7z') || s.endsWith('.tar') || s.endsWith('.gz')) {
        return 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 24 24" fill="%23F59E0B"><path d="M20 6h-8l-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2zm-6 4v2h-2v-2h2zm-2 4h2v2h-2v-2zm-4-4v6H6v-6h2z"/></svg>';
    }
    if (s.endsWith('.pdf')) {
        return 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 24 24" fill="%23EF4444"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-9.5 8.5h-2v3H6V8h3.5c1.1 0 2 .9 2 2v.5c0 1.1-.9 2-2 2zm8 0h-2.5v1.5H17v1.5h-2v1.5h-1.5V8h4v2h-.5zm-5 4.5h-1.5V8H14v6.5h-1.5z"/></svg>';
    }
    if (s.includes('mega.nz') || s.includes('mega.io') || s.includes('mega.co.nz')) {
        return 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 24 24" fill="%23DC2626"><circle cx="12" cy="12" r="10"/><path fill="%23FFFFFF" d="M7 8.5v7l3.5-3.5 3.5 3.5v-7l-3.5 3.5z"/></svg>';
    }
    if (s.includes('terabox') || s.includes('1024tera') || s.includes('mirrobox') || s.includes('nephobox')) {
        return 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 24 24" fill="%230284C7"><circle cx="12" cy="12" r="10"/><path fill="%23FFFFFF" d="M12 6a4 4 0 0 0-4 4c0 .3.03.6.1.9A3.5 3.5 0 0 0 6 14.5a3.5 3.5 0 0 0 3.5 3.5h7a3.5 3.5 0 0 0 3.5-3.5c0-1.6-1.1-3-2.6-3.4.1-.3.1-.7.1-1.1a4 4 0 0 0-4-4z"/></svg>';
    }
    return DEFAULT_VIDEO_THUMB;
}

function handleThumbnailError(img) {
    const orig = img.dataset.origSrc || img.src;
    if (orig && !img.dataset.proxied && !orig.startsWith('data:') && !orig.includes('/api/thumbnail-proxy')) {
        img.dataset.proxied = 'true';
        img.src = '/api/thumbnail-proxy?url=' + encodeURIComponent(orig);
    } else {
        img.src = getDefaultFileThumb(orig);
    }
}

function getSafeThumbnailUrl(url, title = '') {
    if (!url) return getDefaultFileThumb(title);
    if (url.startsWith('data:') || url.startsWith('/') || url.startsWith('http://127.0.0.1')) {
        return url;
    }
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
            showToast(data.error_message || 'No downloadable streams detected on this page.', 4500);
            return;
        }

        currentAnalysis = data;
        renderVideoPreview(data);
    } catch (err) {
        statusText.style.display = 'none';
        showToast('Network or server error while analyzing URL.', 4500);
    }
}

function renderVideoPreview(data) {
    const previewCard = document.getElementById('video-preview-card');
    const thumb = document.getElementById('preview-thumbnail');
    const title = document.getElementById('preview-title');
    const meta = document.getElementById('preview-meta');
    const formatsContainer = document.getElementById('formats-list');
    const downloadAllBtn = document.getElementById('btn-download-all');
    const downloadAllCount = document.getElementById('download-all-count');

    thumb.dataset.origSrc = data.thumbnail || '';
    thumb.dataset.proxied = '';
    thumb.src = getSafeThumbnailUrl(data.thumbnail);
    title.textContent = data.title;

    if (data.is_folder) {
        meta.textContent = `📁 Cloud Folder • ${data.detected_count} Files Available`;
    } else {
        meta.textContent = `Duration: ${data.duration_str} • ${data.detected_count} Streams Found`;
    }

    // Handle Download All Files button for folders / multi-file sets
    if (downloadAllBtn) {
        if (data.is_folder || (data.formats && data.formats.length > 1 && data.formats.some(f => f.filename))) {
            downloadAllBtn.style.display = 'block';
            if (downloadAllCount) downloadAllCount.textContent = data.formats.length;
        } else {
            downloadAllBtn.style.display = 'none';
        }
    }

    formatsContainer.innerHTML = '';
    selectedFormat = data.formats[0] || null;

    data.formats.forEach((fmt, index) => {
        const item = document.createElement('div');
        item.className = `format-item ${index === 0 ? 'selected' : ''}`;
        const displayLabel = fmt.filename || fmt.quality_label;
        const subInfo = fmt.filesize_str ? `${fmt.codec || 'auto'} • ${fmt.filesize_str}` : (fmt.resolution || 'Auto');
        item.innerHTML = `
            <div style="flex:1; min-width:0; overflow:hidden;">
                <div class="format-label" style="text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">${displayLabel} (${(fmt.ext || 'MP4').toUpperCase()})</div>
                <div class="format-info">${subInfo}</div>
            </div>
            <div style="font-size: 11px; font-weight: bold; color: #818CF8; margin-left:8px; white-space:nowrap;">
                ${fmt.has_audio && fmt.has_video ? '✓ Video + Audio' : (fmt.has_video ? 'Video' : (fmt.has_audio ? 'Audio Only' : 'File'))}
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

async function downloadAllAnalyzedFiles() {
    if (!currentAnalysis || !currentAnalysis.formats || currentAnalysis.formats.length === 0) return;
    const items = currentAnalysis.formats;
    showToast(`🚀 Queuing ${items.length} files for download...`, 4000);

    let started = 0;
    for (const fmt of items) {
        try {
            const fileName = fmt.filename || fmt.quality_label;
            await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: currentAnalysis.source_url,
                    filename: fileName,
                    title: fileName,
                    quality_label: fmt.quality_label,
                    format_selector: fmt.download_selector || 'best',
                    direct_url: fmt.direct_url,
                    thumbnail: currentAnalysis.thumbnail && !currentAnalysis.thumbnail.startsWith('data:') ? currentAnalysis.thumbnail : '',
                    duration: currentAnalysis.duration
                })
            });
            started++;
        } catch (e) {
            console.error('Error queuing file:', e);
        }
    }
    showToast(`✅ ${started} files queued for download!`, 4000);
    switchTab('downloads');
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
        if (extBtn) extBtn.style.display = 'inline-block';

        // Route through local stream proxy to prevent 403 Forbidden on mobile
        player.onerror = () => {
            if (errBox) {
                errBox.style.display = 'block';
            }
        };

        const refUrl = (currentAnalysis && currentAnalysis.source_url) ? encodeURIComponent(currentAnalysis.source_url) : '';
        player.src = `/api/stream-proxy?url=${encodeURIComponent(streamUrl)}&referer=${refUrl}`;
        modal.classList.add('active');
        player.play().catch(e => console.log('Autoplay deferred:', e));
    } else {
        showToast('⚡ Starting download so you can watch in HD player!');
        startDownload(currentAnalysis, selectedFormat || currentAnalysis.formats[0]);
    }
}

// Open analyzed video directly in Phone Video Player (VLC / MX / Gallery)
async function openPreviewInPhonePlayer() {
    if (!currentAnalysis) return;
    let streamUrl = currentAnalysis.direct_url;
    if (!streamUrl && selectedFormat && selectedFormat.direct_url) {
        streamUrl = selectedFormat.direct_url;
    }
    if (!streamUrl && currentAnalysis.formats && currentAnalysis.formats.length > 0) {
        streamUrl = currentAnalysis.formats[0].direct_url;
    }

    if (!streamUrl) {
        showToast('⚡ Starting download to open in phone player...');
        startDownload(currentAnalysis, selectedFormat || currentAnalysis.formats[0]);
        return;
    }

    showToast('📱 Launching in Phone Video Player...', 3000);
    try {
        const res = await fetch('/api/media/open-url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: streamUrl })
        });
        const data = await res.json();
        if (!data.success) {
            watchAnalyzedVideo();
        }
    } catch (_) {
        watchAnalyzedVideo();
    }
}

async function startDownload(analysis, fmt) {
    if (!analysis || !fmt) return;
    const targetUrl = fmt.direct_url || analysis.source_url;
    const clean = (targetUrl || '').split('?')[0].toLowerCase();
    if (clean.endsWith('.svg') || clean.endsWith('.png') || clean.endsWith('.jpg') || clean.endsWith('.jpeg') || clean.endsWith('.gif') || clean.endsWith('.webp')) {
        showToast('⚠️ Cannot download image/SVG file directly.', 4000);
        return;
    }

    const titleToUse = fmt.filename || (analysis.is_folder ? fmt.quality_label : analysis.title);

    try {
        const res = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: analysis.source_url,
                filename: fmt.filename || '',
                title: titleToUse,
                quality_label: fmt.quality_label,
                format_selector: fmt.download_selector || 'best',
                direct_url: fmt.direct_url,
                thumbnail: analysis.thumbnail && !analysis.thumbnail.startsWith('data:') ? analysis.thumbnail : '',
                duration: analysis.duration
            })
        });
        const result = await res.json();
        if (result.success) {
            showToast(`⬇ Download started: ${titleToUse}`);
            switchTab('downloads');
        }
    } catch (err) {
        showToast('Failed to start download.', 3500);
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
        loadDownloads(false);
    }, 2000);

    // Immediate reactive refresh when returning to app or unlocking phone
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            loadDownloads(false);
            checkClipboardForVideo();
            checkOverlayPermissionStatus();
        }
    });
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
                    ? ` • ${(item.speed / (1024 * 1024)).toFixed(2)} MB/s <span class="turbo-badge">⚡ Turbo 8x</span>` : '';
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
            speedText = ` • ${(item.speed / (1024 * 1024)).toFixed(2)} MB/s <span class="turbo-badge">⚡ Turbo 8x</span>`;
        }

        const thumbSrc = getSafeThumbnailUrl(item.thumbnail, item.title);
        const isNonVideo = /\.(apk|xapk|zip|rar|7z|tar|gz|pdf|doc|docx|xls|xlsx|ppt|pptx|iso|dmg|exe)$/i.test(item.title || '');

        return `
            <div class="download-item" id="dl-card-${item.id}">
                <div class="dl-header">
                    <img class="dl-thumb" src="${thumbSrc}" referrerpolicy="no-referrer" onerror="handleThumbnailError(this)" data-orig-src="${item.thumbnail || item.title || ''}" />
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
                ${item.status === 'failed' && item.error_message ? `
                    <div style="font-size:11px; color:#EF4444; margin-top:6px; word-break:break-all;">⚠️ ${item.error_message}</div>
                ` : ''}
                <div class="dl-actions">
                    ${isDownloading ? `<button class="btn btn-secondary btn-sm" onclick="pauseDownload('${item.id}')">⏸ Pause</button>` : ''}
                    ${isPaused ? `<button class="btn btn-primary btn-sm" onclick="resumeDownload('${item.id}')">▶ Resume</button>` : ''}
                    ${item.status === 'failed' ? `
                        <button class="btn btn-primary btn-sm" onclick="openUrlInBrowser('${encodeURIComponent(item.url)}')">🌐 Open in Browser</button>
                        <button class="btn btn-secondary btn-sm" onclick="retryDownload('${item.id}', '${encodeURIComponent(item.url)}')">🔄 Retry</button>
                    ` : ''}
                    ${!isCompleted ? `<button class="btn btn-danger btn-sm" onclick="cancelDownload('${item.id}')">✕ Cancel</button>` : ''}
                    ${isCompleted ? (isNonVideo ? `
                        <button class="btn btn-primary btn-sm" onclick="openInPhonePlayer('${item.id}')">📂 Open File</button>
                        <button class="btn btn-danger btn-sm" onclick="deleteDownload('${item.id}')">🗑 Delete</button>
                    ` : `
                        <button class="btn btn-primary btn-sm" onclick="playVideo('${item.id}')">▶ Play</button>
                        <button class="btn btn-secondary btn-sm" onclick="openInPhonePlayer('${item.id}')" title="Open in phone gallery or video player">📱 Open</button>
                        <button class="btn btn-secondary btn-sm" onclick="hideInVault('${item.id}')">🔒 Hide in Vault</button>
                        <button class="btn btn-danger btn-sm" onclick="deleteDownload('${item.id}')">🗑 Delete</button>
                    `) : ''}
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

        // Update Download Save Location UI
        const dirDisplay = document.getElementById('current-download-dir-display');
        const dirInput = document.getElementById('input-custom-download-dir');
        const badge = document.getElementById('dir-writable-badge');
        const presetsContainer = document.getElementById('preset-folders-container');

        if (dirDisplay && settings.download_folder) {
            dirDisplay.textContent = settings.download_folder;
        }
        if (dirInput && settings.download_folder) {
            dirInput.value = settings.download_folder;
        }
        if (badge) {
            if (settings.is_writable) {
                badge.textContent = '✓ Writable & Ready';
                badge.style.background = 'rgba(16,185,129,0.15)';
                badge.style.color = '#34D399';
            } else {
                badge.textContent = '⚠️ Folder Not Writable - Select another folder';
                badge.style.background = 'rgba(239,68,68,0.15)';
                badge.style.color = '#F87171';
            }
        }

        if (presetsContainer && Array.isArray(settings.preset_folders)) {
            presetsContainer.innerHTML = '';
            settings.preset_folders.forEach(preset => {
                const btn = document.createElement('button');
                btn.className = 'btn btn-secondary btn-sm';
                btn.style.cssText = 'text-align:left; justify-content:flex-start; padding:8px 10px; font-size:11px;';
                btn.innerHTML = `<span style="font-weight:700; color:#EEF2FF;">${preset.label}</span><br><span style="color:#94A3B8; font-size:10px;">${preset.path}</span>`;
                btn.onclick = () => saveCustomDownloadDir(preset.path);
                presetsContainer.appendChild(btn);
            });
        }

        // Check All Files Access permission status on Android 11+
        try {
            const permRes = await fetch('/api/storage/permission-status');
            if (permRes.ok) {
                const permData = await permRes.json();
                const storageBanner = document.getElementById('storage-perm-banner');
                if (storageBanner) {
                    storageBanner.style.display = (permData.is_android && !permData.all_files_access) ? 'block' : 'none';
                }
            }
        } catch (_) {}

        await checkOverlayPermissionStatus();
    } catch (err) {
        console.error('Error loading settings:', err);
    }
}

async function saveCustomDownloadDir(customPath) {
    const input = document.getElementById('input-custom-download-dir');
    const path = customPath || (input ? input.value.trim() : '');
    if (!path) {
        showToast('⚠️ Please enter or select a folder path.');
        return;
    }

    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ download_folder: path })
        });
        const data = await res.json();
        if (data.success) {
            const folderName = path.split('/').pop().split('\\').pop() || path;
            showToast(`✅ Download folder set to: ${folderName}`, 3500);
            await loadSettings();
            await loadStorageStats();
        } else {
            showToast('❌ ' + (data.error || 'Failed to update folder.'), 4500);
        }
    } catch (err) {
        showToast('Failed to save download location.', 3500);
    }
}

// --- Visual Interactive Folder Picker ---
let folderPickerCurrentPath = '';

async function openFolderPicker() {
    const modal = document.getElementById('folder-picker-modal');
    if (!modal) return;
    modal.classList.add('active');

    const dirDisplay = document.getElementById('current-download-dir-display');
    const currentPath = dirDisplay ? dirDisplay.textContent.trim() : '';
    await browseToFolder(currentPath || '');
}

function closeFolderPicker() {
    const modal = document.getElementById('folder-picker-modal');
    if (modal) modal.classList.remove('active');
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

async function browseToFolder(path) {
    const listEl = document.getElementById('folder-picker-list');
    const pathEl = document.getElementById('folder-picker-current-path');
    const shortcutsEl = document.getElementById('folder-picker-shortcuts');

    if (listEl) listEl.innerHTML = '<div style="text-align:center; padding:20px; color:#94A3B8; font-size:12px;">Loading folders...</div>';

    try {
        const res = await fetch(`/api/storage/browse?path=${encodeURIComponent(path || '')}`);
        const data = await res.json();
        folderPickerCurrentPath = data.current_path;
        if (pathEl) pathEl.textContent = data.current_path;

        // Render quick shortcut pills via DOM elements
        if (shortcutsEl && Array.isArray(data.shortcuts)) {
            shortcutsEl.innerHTML = '';
            data.shortcuts.forEach(sc => {
                const pill = document.createElement('div');
                pill.className = 'folder-shortcut-pill';
                pill.innerHTML = `<span>${sc.icon}</span> <span>${escapeHtml(sc.label)}</span>`;
                pill.onclick = () => browseToFolder(sc.path);
                shortcutsEl.appendChild(pill);
            });
        }

        // Render folder rows via DOM elements
        if (listEl) {
            listEl.innerHTML = '';
            if (data.parent_path) {
                const upRow = document.createElement('div');
                upRow.className = 'folder-row is-up';
                upRow.innerHTML = `
                    <div class="folder-row-title">
                        <span>⬆</span> <span>.. (Parent Directory)</span>
                    </div>
                    <span style="font-size:11px; color:#64748B;">Back</span>
                `;
                upRow.onclick = () => browseToFolder(data.parent_path);
                listEl.appendChild(upRow);
            }

            if (data.directories && data.directories.length > 0) {
                data.directories.forEach(d => {
                    const row = document.createElement('div');
                    row.className = 'folder-row';
                    row.innerHTML = `
                        <div class="folder-row-title">
                            <span>📁</span> <span style="word-break:break-all;">${escapeHtml(d.name)}</span>
                        </div>
                        <span style="font-size:10px; color:${d.is_writable ? '#34D399' : '#EF4444'};">
                            ${d.is_writable ? '✓ Writable' : '🔒 Protected'}
                        </span>
                    `;
                    row.onclick = () => browseToFolder(d.path);
                    listEl.appendChild(row);
                });
            } else {
                listEl.innerHTML = '<div style="text-align:center; padding:20px; color:#94A3B8; font-size:12px;">No subfolders inside this directory.<br>Tap "Select This Folder" to use it.</div>';
            }
        }
    } catch (err) {
        if (listEl) listEl.innerHTML = '<div style="text-align:center; padding:20px; color:#EF4444; font-size:12px;">Failed to load directories.</div>';
    }
}

async function confirmSelectFolder() {
    if (!folderPickerCurrentPath) return;
    closeFolderPicker();
    await saveCustomDownloadDir(folderPickerCurrentPath);
}

async function promptCreateNewFolder() {
    if (!folderPickerCurrentPath) return;
    const name = prompt('Enter name for new folder:');
    if (!name || !name.trim()) return;

    try {
        const res = await fetch('/api/storage/create-dir', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ parent_path: folderPickerCurrentPath, name: name.trim() })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`✅ Created folder: ${data.name}`);
            await browseToFolder(data.path);
        } else {
            showToast(`❌ ${data.error || 'Failed to create folder'}`);
        }
    } catch (err) {
        showToast('Error creating folder.');
    }
}

async function requestAllFilesAccess() {
    showToast('Opening Android Storage Settings... Please enable All Files Access.', 4000);
    try {
        await fetch('/api/storage/request-full-access', { method: 'POST' });
    } catch (_) {}
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
                        const rawUrl = match[1].replace(/[.,;:()\[\]{}<>"']+$/, '');
                        const clean = rawUrl.split('?')[0].toLowerCase();
                        if (!clean.endsWith('.svg') && !clean.endsWith('.png') && !clean.endsWith('.jpg') && !clean.endsWith('.jpeg') && !clean.endsWith('.gif') && !clean.endsWith('.webp') && !clean.endsWith('.ico') && !clean.endsWith('.css') && !clean.endsWith('.js')) {
                            foundUrl = rawUrl;
                        }
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

    showToast('🔍 Checking clipboard for download link...');
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

    showToast('📋 Copy a video or download link in any app, then tap ⚡ to download!');
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
    try {
        const statusRes = await fetch('/api/overlay/status');
        if (statusRes.ok) {
            const statusData = await statusRes.json();
            if (statusData.is_android && !statusData.can_draw) {
                // Show permission guide modal directly
                const modal = document.getElementById('overlay-permission-modal');
                if (modal) {
                    modal.classList.add('active');
                    return;
                }
            }
        }
    } catch (_) {}

    showToast('🚀 Bringing Floating Bubble onto screen...', 3000);
    try {
        const res = await fetch('/api/overlay/show', { method: 'POST' });
        const data = await res.json();
        if (data.needs_permission) {
            const modal = document.getElementById('overlay-permission-modal');
            if (modal) modal.classList.add('active');
        } else if (data.message) {
            showToast(data.message, 5000);
        }
        await checkOverlayPermissionStatus();
    } catch (err) {
        showToast('Failed to start floating bubble.');
    }
}

function closeOverlayModal() {
    const modal = document.getElementById('overlay-permission-modal');
    if (modal) modal.classList.remove('active');
}

async function requestOverlayPermissionAndCloseModal() {
    closeOverlayModal();
    showToast('⚙️ Opening Android Settings... Please enable Appear On Top.', 4000);
    await requestOverlayPermission();
}

// 1-Click Direct Download handler for URL input box
async function onDirectDownloadClicked() {
    let url = document.getElementById('url-input').value.trim();
    if (!url) {
        showToast('Checking clipboard for download link...', 2000);
        await checkClipboardForVideo();
        url = detectedVideoUrl || document.getElementById('url-input').value.trim();
    }
    if (!url) {
        showToast('Please paste or type a video or cloud/file URL first!', 3000);
        return;
    }
    const clean = url.split('?')[0].toLowerCase();
    if (clean.endsWith('.svg') || clean.endsWith('.png') || clean.endsWith('.jpg') || clean.endsWith('.jpeg') || clean.endsWith('.gif') || clean.endsWith('.webp')) {
        showToast('⚠️ Please enter a video or cloud/file link, not an image/SVG file.', 4000);
        return;
    }
    quickAutoDownloadUrl(url);
}

async function retryDownload(id, encodedUrl) {
    showToast('🔄 Retrying download...', 3000);
    if (id) {
        try {
            const res = await fetch(`/api/downloads/${id}/resume`, { method: 'POST' });
            if (res.ok) {
                loadDownloads();
                return;
            }
        } catch (_) {}
    }
    const rawUrl = decodeURIComponent(encodedUrl || '');
    if (rawUrl) {
        quickAutoDownloadUrl(rawUrl);
    }
}

// Export functions to window for HTML onclick attributes
window.quickAutoDownloadDetected = quickAutoDownloadDetected;
window.onDirectDownloadClicked = onDirectDownloadClicked;
window.retryDownload = retryDownload;
window.onFabClicked = onFabClicked;
window.requestOverlayPermission = requestOverlayPermission;
window.requestOverlayPermissionAndCloseModal = requestOverlayPermissionAndCloseModal;
window.closeOverlayModal = closeOverlayModal;
window.showFloatingBubble = showFloatingBubble;
window.openPreviewInPhonePlayer = openPreviewInPhonePlayer;
window.openInPhonePlayer = openInPhonePlayer;
window.openCurrentInExternalPlayer = openCurrentInExternalPlayer;
window.appGoBack = appGoBack;
window.openFolderPicker = openFolderPicker;
window.closeFolderPicker = closeFolderPicker;
window.browseToFolder = browseToFolder;
window.confirmSelectFolder = confirmSelectFolder;
window.promptCreateNewFolder = promptCreateNewFolder;
window.requestAllFilesAccess = requestAllFilesAccess;
window.saveCustomDownloadDir = saveCustomDownloadDir;

// --- In-App Browser & Proxy Sniffer ---
let currentSniffedStream = null;
let browserHistory = [];
let browserHistoryIdx = -1;

function initBrowser() {
    const backBtn = document.getElementById('btn-browser-back');
    const forwardBtn = document.getElementById('btn-browser-forward');
    const refreshBtn = document.getElementById('btn-browser-refresh');
    const goBtn = document.getElementById('btn-browser-go');
    const input = document.getElementById('browser-url-input');
    const iframe = document.getElementById('browser-webview');
    const detectBtn = document.getElementById('btn-browser-detect');
    const sniffBanner = document.getElementById('browser-sniff-banner');
    const sniffTitle = document.getElementById('sniff-banner-title');
    const sniffUrl = document.getElementById('sniff-banner-url');
    const sniffDlBtn = document.getElementById('btn-browser-sniff-dl');
    const sniffCloseBtn = document.getElementById('btn-browser-sniff-close');

    function navigateBrowser(url, recordHistory = true) {
        if (!url) return;
        let target = url.trim();
        if (!target.startsWith('http://') && !target.startsWith('https://')) {
            target = 'https://' + target;
        }
        if (input) input.value = target;
        if (sniffBanner) sniffBanner.style.display = 'none';
        currentSniffedStream = null;

        if (recordHistory) {
            if (browserHistoryIdx < browserHistory.length - 1) {
                browserHistory = browserHistory.slice(0, browserHistoryIdx + 1);
            }
            browserHistory.push(target);
            browserHistoryIdx = browserHistory.length - 1;
        }

        if (iframe) {
            iframe.src = `/api/browser-proxy?url=${encodeURIComponent(target)}`;
        }
    }

    if (backBtn) {
        backBtn.addEventListener('click', () => {
            if (browserHistoryIdx > 0) {
                browserHistoryIdx--;
                const prev = browserHistory[browserHistoryIdx];
                navigateBrowser(prev, false);
            } else {
                showToast('Already at the oldest page in browser history.');
            }
        });
    }

    if (forwardBtn) {
        forwardBtn.addEventListener('click', () => {
            if (browserHistoryIdx < browserHistory.length - 1) {
                browserHistoryIdx++;
                const nxt = browserHistory[browserHistoryIdx];
                navigateBrowser(nxt, false);
            } else {
                showToast('Already at the newest page in browser history.');
            }
        });
    }

    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            const current = (input && input.value) ? input.value.trim() : '';
            if (current) {
                navigateBrowser(current, false);
            } else if (iframe && iframe.src) {
                iframe.src = iframe.src;
            }
        });
    }

    if (goBtn && input) {
        goBtn.addEventListener('click', () => navigateBrowser(input.value));
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') navigateBrowser(input.value);
        });
    }

    if (detectBtn && input) {
        detectBtn.addEventListener('click', () => {
            const url = input.value.trim();
            if (url) {
                switchTab('home');
                const mainInput = document.getElementById('url-input');
                if (mainInput) mainInput.value = url;
                triggerAnalyze(url);
            }
        });
    }

    if (sniffCloseBtn && sniffBanner) {
        sniffCloseBtn.addEventListener('click', () => {
            sniffBanner.style.display = 'none';
        });
    }

    if (sniffDlBtn) {
        sniffDlBtn.addEventListener('click', () => {
            if (currentSniffedStream) {
                const streamToDownload = currentSniffedStream;
                if (sniffBanner) sniffBanner.style.display = 'none';
                quickAutoDownloadUrl(streamToDownload.url);
            }
        });
    }

    // Global listener for stream detection and navigation events from browser proxy iframe
    window.addEventListener('message', (event) => {
        if (!event.data) return;

        if (event.data.type === 'BROWSER_NAVIGATED' && event.data.url) {
            const newUrl = event.data.url;
            if (input && newUrl) {
                input.value = newUrl;
                if (browserHistory[browserHistoryIdx] !== newUrl) {
                    if (browserHistoryIdx < browserHistory.length - 1) {
                        browserHistory = browserHistory.slice(0, browserHistoryIdx + 1);
                    }
                    browserHistory.push(newUrl);
                    browserHistoryIdx = browserHistory.length - 1;
                }
            }
        }

        if (event.data.type === 'SNIFFED_STREAM') {
            const stream = event.data;
            if (!stream.url) return;
            currentSniffedStream = stream;
            if (sniffBanner && sniffTitle && sniffUrl) {
                sniffTitle.textContent = '⚡ ' + (stream.title || 'Video Stream Detected!');
                sniffUrl.textContent = stream.url.substring(0, 60) + '...';
                sniffBanner.style.display = 'flex';
            }
            showToast('⚡ Video stream detected! Tap Download in Browser tab.', 3500);
        }
    });
}

function openUrlInBrowser(encodedUrl) {
    const rawUrl = decodeURIComponent(encodedUrl || '');
    if (!rawUrl) return;
    switchTab('browser');
    const input = document.getElementById('browser-url-input');
    const iframe = document.getElementById('browser-webview');
    const sniffBanner = document.getElementById('browser-sniff-banner');
    if (sniffBanner) sniffBanner.style.display = 'none';
    currentSniffedStream = null;
    if (input) input.value = rawUrl;
    if (iframe) {
        if (browserHistoryIdx < browserHistory.length - 1) {
            browserHistory = browserHistory.slice(0, browserHistoryIdx + 1);
        }
        browserHistory.push(rawUrl);
        browserHistoryIdx = browserHistory.length - 1;
        iframe.src = `/api/browser-proxy?url=${encodeURIComponent(rawUrl)}`;
    }
}
window.openUrlInBrowser = openUrlInBrowser;
window.saveCustomDownloadDir = saveCustomDownloadDir;
window.downloadAllAnalyzedFiles = downloadAllAnalyzedFiles;

