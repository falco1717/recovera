(function () {
    'use strict';

    function renderTargets(status) {
        var cell = document.getElementById('recovera-offsite-servers');
        if (!cell) {
            return;
        }
        var targets = Object.keys(status.peers || {}).filter(function (id) {
            return status.peers[id].enabled !== false;
        }).map(function (id) {
            var peer = status.peers[id];
            return peer.name + (peer.host ? ' (' + peer.host + ')' : '');
        });
        cell.textContent = targets.length ? targets.join(', ') : 'None';
        cell.title = targets.join('\n');
    }

    function latestSuccess(status, asset) {
        var rule = (status.rules || {})[asset];
        var state = rule && ((status.state || {}).assets || {})[rule.peer_id + ':' + asset];
        if (state && state.last_success) return Number(state.last_success);
        return (status.state && status.state.events || []).reduce(function (latest, event) {
            return event.kind === 'replication-success' && event.asset === asset
                ? Math.max(latest, Number(event.time || 0)) : latest;
        }, 0);
    }

    function renderReplication(status) {
        document.querySelectorAll('table').forEach(function (table) {
            var headers = Array.from(table.querySelectorAll('th')).map(function (header) {
                return (header.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
            });
            var syncedIndex = headers.indexOf('last synced');
            if (syncedIndex < 0) return;
            table.querySelectorAll('tbody tr').forEach(function (row) {
                var link = row.querySelector('a[href*="/agents/"]');
                var match = link && link.getAttribute('href').match(/[0-9a-f]{32}/i);
                var cells = row.querySelectorAll('td');
                if (!match || !cells[syncedIndex]) return;
                var timestamp = latestSuccess(status, match[0].toLowerCase());
                if (timestamp) {
                    cells[syncedIndex].textContent = new Date(timestamp * 1000).toLocaleString();
                    cells[syncedIndex].dataset.recoveraLastSynced = String(timestamp);
                }
            });
        });
    }

    function loadStatus() {
        fetch('/api/recovera/offsite-target/status', {
            credentials: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        }).then(function (response) {
            if (!response.ok) {
                throw new Error(response.statusText);
            }
            return response.json();
        }).then(function (status) {
            renderTargets(status);
            renderReplication(status);
        }).catch(function () {
            // Leave the native value in place if this user cannot read the
            // Recovera replication status endpoint.
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadStatus);
    } else {
        loadStatus();
    }
}());
