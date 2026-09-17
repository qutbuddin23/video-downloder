/**
 * Universal Video Downloader - Modern Android Material 3 Frontend Logic
 */

let currentAnalysis = null;
let selectedFormat = null;
let currentTab = 'home';
let downloadFilter = 'all';
let pollInterval = null;
let enteredPin = '';
let isPinSetupMode = false;

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initUrlAnalyzer();
    initDownloads();
    initVault();
    initSettings();
    initBrowser();
    startDownloadPolling();
    startOverlayPolling();
    loadStorageStats();
});

// --- Tab Navigation ---
function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetTab = item.dataset.tab;
            switchTab(targetTab);
        });
    });
}

function switchTab(tabId) {
    currentTab = tabId;
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

// --- URL Analysis & Detection ---
function initUrlAnalyzer() {
    const pasteBtn = document.getElementById('btn-paste');
    const analyzeBtn = document.getElementById('btn-analyze');
    const urlInput = document.getElementById('url-input');
    const downloadBtn = document.getElementById('btn-start-download');

    pasteBtn.addEventListener('click', async () => {
        try {
            const text = await navigator.clipboard.readText();
            if (text) {
                urlInput.value = text;
                triggerAnalyze(text);
            }
        } catch (err) {
            console.error('Clipboard access failed:', err);
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

    thumb.src = data.thumbnail || 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600';
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
    }, 1500);
}

async function loadDownloads(showLoading = true) {
    try {
        const res = await fetch(`/api/downloads?filter=${downloadFilter}`);
        const items = await res.json();
        renderDownloadsList(items);
    } catch (err) {
        console.error('Error fetching downloads:', err);
    }
}

function renderDownloadsList(items) {
    const list = document.getElementById('downloads-list');
    if (!items || items.length === 0) {
        list.innerHTML = `<div style="text-align:center; padding: 40px 10px; color: #94A3B8;">No downloads found in this tab.</div>`;
        return;
    }

    list.innerHTML = items.map(item => {
        const isDownloading = item.status === 'downloading';
        const isPaused = item.status === 'paused';
        const isCompleted = item.status === 'completed';

        let speedText = '';
        if (isDownloading && item.speed > 0) {
            speedText = ` • ${(item.speed / (1024 * 1024)).toFixed(2)} MB/s`;
        }

        return `
            <div class="download-item">
                <div class="dl-header">
                    <img class="dl-thumb" src="${item.thumbnail || 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=100'}" />
                    <div class="dl-info">
                        <div class="dl-title">${item.title}</div>
                        <div class="dl-meta">${item.quality} • Status: <b style="color:#818CF8">${item.status.toUpperCase()}</b>${speedText}</div>
                    </div>
                </div>
                ${!isCompleted ? `
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill" style="width: ${item.progress}%"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:11px; color:#94A3B8;">
                        <span>${item.progress.toFixed(1)}%</span>
                        <span>${((item.downloaded_bytes || 0) / (1024*1024)).toFixed(1)} MB</span>
                    </div>
                ` : ''}
                <div class="dl-actions">
                    ${isDownloading ? `<button class="btn btn-secondary btn-sm" onclick="pauseDownload('${item.id}')">Pause</button>` : ''}
                    ${isPaused ? `<button class="btn btn-primary btn-sm" onclick="resumeDownload('${item.id}')">Resume</button>` : ''}
                    ${!isCompleted ? `<button class="btn btn-danger btn-sm" onclick="cancelDownload('${item.id}')">Cancel</button>` : ''}
                    ${isCompleted ? `
                        <button class="btn btn-primary btn-sm" onclick="playVideo('${item.id}')">▶ Play</button>
                        <button class="btn btn-secondary btn-sm" onclick="hideInVault('${item.id}')">🔒 Hide in Vault</button>
                        <button class="btn btn-danger btn-sm" onclick="deleteDownload('${item.id}')">Delete</button>
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
        const res = await fetch('/api/vault/hide', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ download_id: id })
        });
        const result = await res.json();
        if (result.success) {
            alert('Video encrypted and moved into Private Vault!');
            loadDownloads();
            loadStorageStats();
        } else {
            alert(result.detail || 'Please unlock the Private Vault first.');
            switchTab('vault');
        }
    } catch (err) {
        alert('Vault error.');
    }
}

// --- Private Vault ---
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
            pinTitle.innerHTML = 'Enter Vault PIN<br><span style="font-size:12px; color:#818CF8; font-weight:normal;">(Password: <b>7232</b>)</span>';
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
                switchTab('home');
                const urlInput = document.getElementById('url-input');
                if (urlInput) {
                    urlInput.value = data.url;
                    triggerAnalyze(data.url);
                }
            }
        } catch (e) {
            // Ignore polling errors
        }
    }, 1800);
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

        list.innerHTML = items.map(item => `
            <div class="download-item" style="border-left: 3px solid #EC4899;">
                <div class="dl-header">
                    <img class="dl-thumb" src="${item.thumbnail || 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=100'}" />
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
        `).join('');
    } catch (err) {
        console.error('Error fetching vault items:', err);
    }
}

async function restoreVaultVideo(id) {
    try {
        const res = await fetch(`/api/vault/restore/${id}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            alert('Video restored to public Downloads!');
            checkVaultStatus();
            loadStorageStats();
        }
    } catch (err) {
        alert('Restore error.');
    }
}

// --- Video Player Modal ---
function playVideo(downloadId) {
    const modal = document.getElementById('player-modal');
    const player = document.getElementById('media-player');
    player.src = `/media/stream/${downloadId}`;
    modal.classList.add('active');
    player.play();
}

async function playVaultVideo(vaultId) {
    try {
        const res = await fetch(`/api/vault/play/${vaultId}`);
        const data = await res.json();
        if (data.stream_url) {
            const modal = document.getElementById('player-modal');
            const player = document.getElementById('media-player');
            player.src = data.stream_url;
            modal.classList.add('active');
            player.play();
        }
    } catch (err) {
        alert('Failed to stream private video.');
    }
}

function closePlayer() {
    const modal = document.getElementById('player-modal');
    const player = document.getElementById('media-player');
    player.pause();
    player.src = '';
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
        alert(`Cleaned ${data.freed_str} of temporary and incomplete files.`);
        loadStorageStats();
    } catch (err) {
        alert('Error cleaning files.');
    }
}

async function initSettings() {
    const overlayToggle = document.getElementById('toggle-floating-button');
    if (overlayToggle) {
        overlayToggle.addEventListener('change', async () => {
            await fetch('/api/overlay/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: overlayToggle.checked })
            });
        });
    }
}

async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        const settings = await res.json();
        const toggle = document.getElementById('toggle-floating-button');
        if (toggle) {
            toggle.checked = settings.floating_button_enabled === 'true';
        }
    } catch (err) {
        console.error('Error loading settings:', err);
    }
}

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
