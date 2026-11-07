(function () {
    'use strict';

    const API_ROOT = '/api/recovera/offsite-target/';
    const RELAY_TITLES = new Set([
        'datto relay forced login',
        'recovera relay forced login'
    ]);
    const AGENT_PAIR_EMPTY_REPLY = /Pairing failed:\s*CURL Error:\s*https:\/\/[^\s/:]+:25567\/pair:\s*Empty reply from server/i;
    const AGENT_PAIR_EXPLANATION = 'Pairing failed: the agent rejected this appliance\'s certificate. ' +
        'The agent is probably already paired with another Recovera appliance or was installed with a different ' +
        'Recovera pairing CA. An agent can be protected by only one appliance. Keep it paired to its current ' +
        'appliance and use Configure → Off-site Target to replicate its backups.';
    let availableRelease = null;
    let currentPolicy = {channel: 'stable', window: {start: 21, end: 5}};

    function normalizedText(element) {
        return (element.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
    }

    function explainAgentPairingFailure(root) {
        if (!root) return;
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        const matches = [];
        while (walker.nextNode()) {
            if (AGENT_PAIR_EMPTY_REPLY.test(walker.currentNode.nodeValue || '')) {
                matches.push(walker.currentNode);
            }
        }
        matches.forEach(function (node) {
            node.nodeValue = (node.nodeValue || '').replace(AGENT_PAIR_EMPTY_REPLY, AGENT_PAIR_EXPLANATION);
        });
    }

    function installAgentPairingErrorExplanation() {
        if (!document.body || document.body.dataset.recoveraPairErrorObserver) return;
        document.body.dataset.recoveraPairErrorObserver = 'true';
        explainAgentPairingFailure(document.body);
        new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                if (mutation.type === 'characterData') {
                    const value = mutation.target.nodeValue || '';
                    if (AGENT_PAIR_EMPTY_REPLY.test(value)) {
                        mutation.target.nodeValue = value.replace(AGENT_PAIR_EMPTY_REPLY, AGENT_PAIR_EXPLANATION);
                    }
                    return;
                }
                mutation.addedNodes.forEach(function (node) {
                    if (node.nodeType === Node.TEXT_NODE) {
                        const value = node.nodeValue || '';
                        if (AGENT_PAIR_EMPTY_REPLY.test(value)) {
                            node.nodeValue = value.replace(AGENT_PAIR_EMPTY_REPLY, AGENT_PAIR_EXPLANATION);
                        }
                    } else if (node.nodeType === Node.ELEMENT_NODE) {
                        explainAgentPairingFailure(node);
                    }
                });
            });
        }).observe(document.body, {childList: true, subtree: true, characterData: true});
    }

    function installAgentRemovalRelease() {
        const assets = window.Datto && Datto.App && Datto.App.Assets;
        const View = assets && assets.RemoveView;
        if (!View || View.prototype.recoveraReleaseInstalled) return false;
        const prototype = View.prototype;
        const nativeRenderView = prototype.renderView;
        prototype.recoveraReleaseInstalled = true;
        prototype.renderView = function () {
            const result = nativeRenderView.apply(this, arguments);
            if (this.context.isShare || !this.$confirmButton || !this.$confirmButton.length) return result;
            const self = this;
            const button = this.$confirmButton.get(0);
            if (button.dataset.recoveraReleaseBound) return result;
            button.dataset.recoveraReleaseBound = 'true';
            button.addEventListener('click', function (event) {
                if (button.dataset.recoveraReleased === 'true' ||
                    button.dataset.recoveraRemoveAnyway === 'true') return;
                event.preventDefault();
                event.stopImmediatePropagation();
                button.disabled = true;
                const originalText = button.textContent;
                button.textContent = 'Releasing agent…';
                request('agent-release', 'POST', {asset: self.context.assetKey}).then(function () {
                    button.dataset.recoveraReleased = 'true';
                    button.disabled = false;
                    button.textContent = originalText;
                    button.click();
                }).catch(function (error) {
                    button.disabled = false;
                    button.dataset.recoveraRemoveAnyway = 'true';
                    button.textContent = 'Remove anyway';
                    let warning = self.$removeModal.find('.recovera-agent-release-warning');
                    if (!warning.length) {
                        warning = window.jQuery('<div class="alert alert-warning recovera-agent-release-warning mt-3">');
                        self.$confirmInput.closest('.modal-body').append(warning);
                    }
                    warning.text(error.message + ' Removing anyway will require a local agent release before another appliance can protect it.');
                });
            }, true);
            return result;
        };
        return true;
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

    function addStorageNavigation() {
        if (document.querySelector('a[href="#settingRecoveraStorageExpand"]')) return;
        const filesystemLink = document.querySelector('a[href="#integrityCheckTimeoutNtfsresize"]');
        if (!filesystemLink || !filesystemLink.parentElement) return;
        const link = filesystemLink.cloneNode(false);
        link.href = '#settingRecoveraStorageExpand';
        link.textContent = 'Expand Backup Storage';
        filesystemLink.parentElement.insertBefore(link, filesystemLink.nextSibling);
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

    function createStoragePanel() {
        const panel = document.createElement('div');
        panel.id = 'settingRecoveraStorageExpand';
        panel.className = 'card my-3';
        panel.innerHTML = [
            '<div class="card-body">',
            '<h3 class="text-secondary fw-medium mb-3">Expand Backup Storage</h3>',
            '<p>Use all additional capacity assigned to this appliance\'s backup disk. Existing backups remain in place.</p>',
            '<div id="recovera-storage-message" class="alert d-none" role="alert"></div>',
            '<dl class="row mb-3">',
            '<dt class="col-sm-4">Storage pool</dt><dd id="recovera-storage-pool" class="col-sm-8">Loading…</dd>',
            '<dt class="col-sm-4">Current pool size</dt><dd id="recovera-storage-size" class="col-sm-8">Loading…</dd>',
            '<dt class="col-sm-4">Detected backup disk</dt><dd id="recovera-storage-disk" class="col-sm-8">Loading…</dd>',
            '<dt class="col-sm-4">Additional capacity</dt><dd id="recovera-storage-available" class="col-sm-8">Scanning…</dd>',
            '</dl>',
            '<button id="recovera-storage-expand" class="btn btn-primary" type="button" disabled>Scan and expand to maximum</button>',
            '<p class="text-secondary mt-3 mb-0">The appliance rescans only the dedicated backup disk and refuses unsupported, unhealthy, or operating-system disk layouts.</p>',
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
        const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
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
        return release && release.available && releaseIsNewer(release.version, value.installed_version)
            ? release : null;
    }

    function versionParts(value) {
        const base = String(value || '').replace(/^\d+:/, '').split('-')[0];
        const matches = base.match(/\d+/g);
        return matches ? matches.map(Number) : [];
    }

    function releaseIsNewer(candidate, installed) {
        const next = versionParts(candidate);
        const current = versionParts(installed);
        if (!next.length || !current.length) {
            return String(candidate || '') !== String(installed || '');
        }
        const length = Math.max(next.length, current.length);
        for (let index = 0; index < length; index += 1) {
            const difference = (next[index] || 0) - (current[index] || 0);
            if (difference) return difference > 0;
        }
        return false;
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

    function setStorageMessage(message, success) {
        const box = document.getElementById('recovera-storage-message');
        if (!box) return;
        box.className = 'alert ' + (success ? 'alert-success' : 'alert-danger');
        box.textContent = message;
    }

    function showStorageStatus(value) {
        document.getElementById('recovera-storage-pool').textContent =
            (value.pool || 'Unknown') + ' (' + (value.health || 'Unknown') + ')';
        document.getElementById('recovera-storage-size').textContent =
            bytes(value.pool_size) + ' (' + bytes(value.free) + ' free)';
        document.getElementById('recovera-storage-disk').textContent =
            (value.disk || 'Unknown') + ' — ' + bytes(value.disk_size);
        document.getElementById('recovera-storage-available').textContent = value.expandable
            ? bytes(Math.max(0, Number(value.disk_size) - Number(value.partition_size))) + ' detected'
            : 'No additional guest-visible capacity currently detected';
        document.getElementById('recovera-storage-expand').disabled = !value.supported;
    }

    async function loadStorageStatus() {
        const button = document.getElementById('recovera-storage-expand');
        if (!button) return;
        try {
            showStorageStatus(await request('storage-status'));
        } catch (error) {
            button.disabled = true;
            setStorageMessage(error.message, false);
        }
    }

    async function expandStorage() {
        if (!window.confirm(
            'Rescan the dedicated backup disk and expand its ZFS pool to the maximum available size? Existing backups will remain online.'
        )) return;
        const button = document.getElementById('recovera-storage-expand');
        button.disabled = true;
        button.textContent = 'Scanning and expanding…';
        setStorageMessage('Scanning the backup disk for additional capacity…', true);
        try {
            const value = await request('storage-expand', 'POST', {confirm: 'expand-to-maximum'});
            showStorageStatus(value);
            setStorageMessage(value.message || 'Backup storage expansion completed.', true);
        } catch (error) {
            setStorageMessage(error.message, false);
        } finally {
            button.textContent = 'Scan and expand to maximum';
            await loadStorageStatus();
        }
    }

    function installStoragePanel() {
        if (document.getElementById('settingRecoveraStorageExpand')) return;
        let filesystem = document.getElementById('integrityCheckTimeoutNtfsresize');
        if (!filesystem) {
            for (const title of document.querySelectorAll('h1, h2, h3, h4, h5, h6, legend, .card-title')) {
                if (normalizedText(title) === 'filesystem') {
                    filesystem = sectionFor(title);
                    break;
                }
            }
        }
        if (!filesystem || !filesystem.parentElement) return;
        const panel = createStoragePanel();
        filesystem.parentElement.insertBefore(panel, filesystem.nextSibling);
        addStorageNavigation();
        document.getElementById('recovera-storage-expand').addEventListener('click', expandStorage);
        window.setTimeout(loadStorageStatus, 0);
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
        installAgentPairingErrorExplanation();
        if (!installAgentRemovalRelease()) {
            let attempts = 0;
            const timer = window.setInterval(function () {
                attempts += 1;
                if (installAgentRemovalRelease() || attempts >= 40) window.clearInterval(timer);
            }, 250);
        }
        if (!/^\/configure\/device\/?$/.test(window.location.pathname)) return;
        removeLegacyRelayControl();
        installStoragePanel();
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
