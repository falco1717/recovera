(function () {
    'use strict';

    const API_ROOT = '/api/recovera/offsite-target/';
    const RELAY_TITLES = new Set([
        'datto relay forced login',
        'recovera relay forced login'
    ]);
    let availableRelease = null;

    function normalizedText(element) {
        return (element.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
    }

    function sectionFor(title) {
        const direct = title.closest('.card, .panel, fieldset');
        if (direct) return direct;
        let section = title.parentElement;
        while (section && section.parentElement) {
            const parentText = normalizedText(section.parentElement);
            if (parentText.includes('reboot now') || parentText.includes('schedule a reboot')) break;
            section = section.parentElement;
        }
        return section;
    }

    function removeLegacyRelayControl() {
        let location = null;
        document.querySelectorAll('h1, h2, h3, h4, h5, h6, legend, .card-title').forEach(function (title) {
            if (!RELAY_TITLES.has(normalizedText(title))) return;
            const section = sectionFor(title);
            if (section) {
                location = {parent: section.parentElement, next: section.nextSibling};
                section.remove();
            }
        });
        return location;
    }

    function findRebootSection() {
        for (const title of document.querySelectorAll('h1, h2, h3, h4, h5, h6, legend, .card-title')) {
            if (normalizedText(title) === 'reboot now') return sectionFor(title);
        }
        return null;
    }

    function createPanel() {
        const panel = document.createElement('div');
        panel.id = 'recovera-update-panel';
        panel.className = 'card mb-3';
        panel.innerHTML = [
            '<div class="card-body">',
            '<h3>Recovera Updates</h3>',
            '<p>Install signed Recovera application updates from the configured GitHub channel.</p>',
            '<div id="recovera-update-message" class="alert d-none" role="alert"></div>',
            '<dl class="row mb-3">',
            '<dt class="col-sm-4">Update channel</dt><dd class="col-sm-8"><span class="badge bg-primary">Stable</span></dd>',
            '<dt class="col-sm-4">Installed version</dt><dd id="recovera-installed-version" class="col-sm-8">Loading…</dd>',
            '<dt class="col-sm-4">Available version</dt><dd id="recovera-available-version" class="col-sm-8">Not checked</dd>',
            '<dt class="col-sm-4">GitHub access</dt><dd id="recovera-update-credential" class="col-sm-8">Checking…</dd>',
            '</dl>',
            '<button id="recovera-update-check" class="btn btn-secondary me-2" type="button">Check for updates</button>',
            '<button id="recovera-update-install" class="btn btn-primary" type="button" disabled>Update now</button>',
            '<p class="text-secondary mt-3 mb-0">Updates are downloaded only after signature and checksum verification. Automatic installation is disabled.</p>',
            '</div>'
        ].join('');
        return panel;
    }

    function setMessage(message, success) {
        const box = document.getElementById('recovera-update-message');
        box.className = 'alert ' + (success ? 'alert-success' : 'alert-danger');
        box.textContent = message;
    }

    function bytes(value) {
        const size = Number(value || 0);
        if (!size) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB'];
        const unit = Math.min(units.length - 1, Math.floor(Math.log(size) / Math.log(1024)));
        return (size / Math.pow(1024, unit)).toFixed(unit ? 1 : 0) + ' ' + units[unit];
    }

    async function request(operation, method) {
        const options = {
            method: method || 'GET', credentials: 'same-origin', cache: 'no-store',
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        };
        if (options.method === 'POST') {
            const csrf = document.querySelector('input[name="csrf"]');
            if (!csrf) throw new Error('The page security token is unavailable; reload the page.');
            options.headers['Content-Type'] = 'application/x-www-form-urlencoded;charset=UTF-8';
            options.body = new URLSearchParams({csrf: csrf.value, payload: '{}'});
        }
        const response = await fetch(API_ROOT + operation, options);
        const value = await response.json().catch(function () { return {}; });
        if (!response.ok) throw new Error(value.error || response.statusText);
        return value;
    }

    function showStatus(value) {
        document.getElementById('recovera-installed-version').textContent = value.installed_version || 'Unknown';
        document.getElementById('recovera-update-credential').textContent = value.credential_configured
            ? 'Configured' : 'Not configured — add /etc/recovera/github-token';
        if (value.release) {
            availableRelease = value.release.available ? value.release : null;
            document.getElementById('recovera-available-version').textContent = value.release.available
                ? value.release.version + ' (' + bytes(value.release.download_size) + ')' : 'Up to date';
        }
        document.getElementById('recovera-update-install').disabled = !availableRelease;
    }

    async function loadStatus(check) {
        const button = document.getElementById('recovera-update-check');
        button.disabled = true;
        button.textContent = check ? 'Checking…' : 'Loading…';
        try {
            const value = await request(check ? 'update-check' : 'update-status');
            showStatus(value);
            if (check) setMessage(availableRelease
                ? 'Recovera ' + availableRelease.version + ' is ready to install.'
                : 'This appliance is up to date.', true);
        } catch (error) {
            availableRelease = null;
            document.getElementById('recovera-update-install').disabled = true;
            setMessage(error.message, false);
        } finally {
            button.disabled = false;
            button.textContent = 'Check for updates';
        }
    }

    async function installUpdate() {
        if (!availableRelease || !window.confirm(
            'Install Recovera ' + availableRelease.version + ' now? Active backup and replication jobs should be allowed to finish first.'
        )) return;
        const button = document.getElementById('recovera-update-install');
        button.disabled = true;
        button.textContent = 'Updating…';
        setMessage('Downloading, verifying, and installing the signed update…', true);
        try {
            const value = await request('update-install', 'POST');
            availableRelease = null;
            setMessage(value.message || 'Update installed. Services will restart momentarily.', true);
            document.getElementById('recovera-available-version').textContent = 'Installed';
            window.setTimeout(function () { window.location.reload(); }, 8000);
        } catch (error) {
            setMessage(error.message, false);
            button.disabled = false;
            button.textContent = 'Update now';
        }
    }

    function initialize() {
        if (!/^\/configure\/device\/?$/.test(window.location.pathname)) return;
        const location = removeLegacyRelayControl();
        const panel = createPanel();
        if (location && location.parent) {
            location.parent.insertBefore(panel, location.next);
        } else {
            const reboot = findRebootSection();
            if (!reboot || !reboot.parentElement) return;
            reboot.parentElement.insertBefore(panel, reboot);
        }
        document.getElementById('recovera-update-check').addEventListener('click', function () { loadStatus(true); });
        document.getElementById('recovera-update-install').addEventListener('click', installUpdate);
        loadStatus(false);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, {once: true});
    } else {
        initialize();
    }
}());
