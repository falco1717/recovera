(function () {
    'use strict';

    const API_ROOT = '/api/recovera/offsite-target/';
    const RELAY_TITLES = new Set([
        'datto relay forced login',
        'recovera relay forced login'
    ]);
    let availableRelease = null;
    let currentPolicy = {channel: 'stable', window: {start: 21, end: 5}};

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
        document.querySelectorAll('a.nav-link').forEach(function (link) {
            if (RELAY_TITLES.has(normalizedText(link))) link.remove();
        });
        return location;
    }

    function addUpdateNowNavigation() {
        if (document.querySelector('a[href="#settingRecoveraUpdateNow"]')) return;
        const channelLink = document.querySelector('a[href="#settingUpgradeChannel"]');
        if (!channelLink || !channelLink.parentElement) return;
        const link = channelLink.cloneNode(false);
        link.href = '#settingRecoveraUpdateNow';
        link.textContent = 'Update Now';
        channelLink.parentElement.insertBefore(link, channelLink.nextSibling);
    }

    function findRebootSection() {
        for (const title of document.querySelectorAll('h1, h2, h3, h4, h5, h6, legend, .card-title')) {
            if (normalizedText(title) === 'reboot now') return sectionFor(title);
        }
        return null;
    }

    function createPanel() {
        const panel = document.createElement('div');
        panel.id = 'settingRecoveraUpdateNow';
        panel.className = 'card my-3';
        panel.innerHTML = [
            '<div class="card-body">',
            '<h3 class="text-secondary fw-medium mb-3">Update Now</h3>',
            '<p>Check for and install a signed Recovera application update immediately.</p>',
            '<div id="recovera-update-message" class="alert d-none" role="alert"></div>',
            '<dl class="row mb-3">',
            '<dt class="col-sm-4">Installed version</dt><dd id="recovera-installed-version" class="col-sm-8">Loading…</dd>',
            '<dt class="col-sm-4">Available version</dt><dd id="recovera-available-version" class="col-sm-8">Not checked</dd>',
            '<dt class="col-sm-4">Scheduled checks</dt><dd id="recovera-update-policy-summary" class="col-sm-8">Loading…</dd>',
            '</dl>',
            '<button id="recovera-update-check" class="btn btn-secondary me-2" type="button">Check for updates</button>',
            '<button id="recovera-update-install" class="btn btn-primary" type="button" disabled>Update now</button>',
            '<p class="text-secondary mt-3 mb-0">Every package is verified by its Recovera signature and checksum before installation.</p>',
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

    async function request(operation, method, payload) {
        const options = {
            method: method || 'GET', credentials: 'same-origin', cache: 'no-store',
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        };
        if (options.method === 'POST') {
            const csrf = document.querySelector('input[name="csrf"]');
            if (!csrf) throw new Error('The page security token is unavailable; reload the page.');
            options.headers['Content-Type'] = 'application/x-www-form-urlencoded;charset=UTF-8';
            options.body = new URLSearchParams({csrf: csrf.value, payload: JSON.stringify(payload || {})});
        }
        const response = await fetch(API_ROOT + operation, options);
        const value = await response.json().catch(function () { return {}; });
        if (!response.ok) throw new Error(value.error || response.statusText);
        return value;
    }

    function cachedRelease(value) {
        const release = value && value.updater && value.updater.state && value.updater.state.available;
        return release && release.available ? release : null;
    }

    function showGlobalUpdateBanner(release) {
        const id = 'recovera.upgrade.available';
        const container = document.getElementById('bannerContainer');
        if (!container || !release || sessionStorage.getItem('dismissed-' + id) ||
            container.querySelector('[data-notification-id="' + id + '"]')) return;
        const box = document.createElement('div');
        box.className = 'notificationBox';
        box.dataset.notificationId = id;
        container.appendChild(box);
        if (window.Datto && Datto.Utility && Datto.Utility.EventBus) {
            Datto.Utility.EventBus.dispatch('notification', window, id, 'info', 'alert', {
                templateId: 'globalAlertTemplate',
                type: 'info',
                message: {
                    title: 'Recovera update available',
                    text: 'Recovera ' + release.version + ' is ready to install.'
                },
                buttons: [{
                    text: 'Review update',
                    url: '/configure/device#settingRecoveraUpdateNow'
                }],
                options: {dismissible: true}
            });
        }
    }

    async function initializeUpdateBanner() {
        try {
            const value = await request('update-status');
            showGlobalUpdateBanner(cachedRelease(value));
        } catch (error) {
            // A banner must never interfere with the page it decorates.
        }
    }

    function hour(value) {
        const normalized = Number(value) % 24;
        return (normalized % 12 || 12) + ':00 ' + (normalized >= 12 ? 'PM' : 'AM');
    }

    function reloadSelect(select) {
        if (window.jQuery && typeof window.reloadSingleSelect === 'function') {
            window.reloadSingleSelect(window.jQuery(select));
        }
    }

    async function savePolicy(policy, button) {
        button.disabled = true;
        try {
            const value = await request('update-policy', 'POST', policy);
            currentPolicy = value.policy;
            showPolicy();
            setMessage('Recovera update settings were applied.', true);
        } catch (error) {
            setMessage(error.message, false);
        } finally {
            button.disabled = false;
        }
    }

    function enhanceNativeControls() {
        const channelCard = document.getElementById('settingUpgradeChannel');
        const channel = document.getElementById('upgradeChannel');
        const channelButton = document.getElementById('upgradeChannelApplyButton');
        if (channelCard) {
            const description = channelCard.querySelector('.card-body > p');
            if (description) description.textContent = 'Choose whether this appliance automatically installs signed Recovera stable updates during its Update Window.';
            const alert = channelCard.querySelector('.alert');
            if (alert) alert.textContent = 'Update checks and installation are automatic during the configured window. The appliance reboots automatically when an update requires it.';
        }
        if (channel && channelButton && !channelButton.dataset.recovera) {
            channel.innerHTML = '<option value="stable">Stable</option><option value="none">None</option>';
            channel.value = currentPolicy.channel;
            reloadSelect(channel);
            const replacement = channelButton.cloneNode(true);
            replacement.dataset.recovera = 'true';
            replacement.disabled = false;
            channelButton.replaceWith(replacement);
            replacement.addEventListener('click', function () {
                savePolicy({channel: channel.value, window: currentPolicy.window}, replacement);
            });
        } else if (channel) {
            channel.value = currentPolicy.channel;
            reloadSelect(channel);
        }

        const windowCard = document.getElementById('settingUpdateWindow');
        const start = document.getElementById('updateWindowStartHour');
        const end = document.getElementById('updateWindowEndHour');
        const windowButton = document.getElementById('updateWindowApplyButton');
        if (windowCard) {
            const description = windowCard.querySelector('.card-body > p');
            if (description) description.textContent = 'Choose when this appliance checks for and automatically installs the latest signed Recovera update. Updates may reboot the appliance during this window.';
        }
        if (start && end) {
            start.value = String(currentPolicy.window.start);
            end.value = String((currentPolicy.window.end + 23) % 24);
            reloadSelect(start);
            reloadSelect(end);
        }
        if (start && end && windowButton && !windowButton.dataset.recovera) {
            const replacement = windowButton.cloneNode(true);
            replacement.dataset.recovera = 'true';
            replacement.disabled = false;
            windowButton.replaceWith(replacement);
            replacement.addEventListener('click', function () {
                savePolicy({channel: currentPolicy.channel, window: {
                    start: Number(start.value), end: (Number(end.value) + 1) % 24
                }}, replacement);
            });
        }
    }

    function showPolicy() {
        enhanceNativeControls();
        const summary = document.getElementById('recovera-update-policy-summary');
        if (!summary) return;
        summary.textContent = currentPolicy.channel === 'none' ? 'Disabled' :
            'Stable, ' + hour(currentPolicy.window.start) + '–' + hour(currentPolicy.window.end);
    }

    function showStatus(value) {
        currentPolicy = value.policy || currentPolicy;
        document.getElementById('recovera-installed-version').textContent = value.installed_version || 'Unknown';
        if (value.release) {
            availableRelease = value.release.available ? value.release : null;
            document.getElementById('recovera-available-version').textContent = value.release.available
                ? value.release.version + ' (' + bytes(value.release.download_size) + ')' : 'Up to date';
        }
        document.getElementById('recovera-update-install').disabled = !availableRelease;
        showPolicy();
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
        initializeUpdateBanner();
        if (!/^\/configure\/device\/?$/.test(window.location.pathname)) return;
        removeLegacyRelayControl();
        const oldPanel = document.getElementById('recovera-update-panel');
        if (oldPanel) oldPanel.remove();
        const channel = document.getElementById('settingUpgradeChannel');
        if (!channel || !channel.parentElement) return;
        let panel = document.getElementById('settingRecoveraUpdateNow');
        if (!panel) {
            panel = createPanel();
            channel.parentElement.insertBefore(panel, channel.nextSibling);
        }
        addUpdateNowNavigation();
        document.getElementById('recovera-update-check').addEventListener('click', function () { loadStatus(true); });
        document.getElementById('recovera-update-install').addEventListener('click', installUpdate);
        window.setTimeout(function () { loadStatus(false); }, 0);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, {once: true});
    } else {
        initialize();
    }
}());
