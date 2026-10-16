(function () {
    'use strict';

    var replicationStatus = null;
    var replicationObserver = null;

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
        var table = document.getElementById('replicationStatusTable');
        if (!table) return;
        table.querySelectorAll('tbody tr[data-asset]').forEach(function (row) {
            var asset = (row.dataset.asset || '').toLowerCase();
            var cell = row.querySelectorAll('td')[1];
            var timestamp = latestSuccess(status, asset);
            if (cell && timestamp && cell.dataset.recoveraLastSynced !== String(timestamp)) {
                cell.textContent = new Date(timestamp * 1000).toLocaleString();
                cell.dataset.recoveraLastSynced = String(timestamp);
            }
        });
    }

    function observeReplication() {
        var body = document.querySelector('#replicationStatusTable tbody');
        if (!body || replicationObserver) return;
        replicationObserver = new MutationObserver(function () {
            if (replicationStatus) renderReplication(replicationStatus);
        });
        replicationObserver.observe(body, {childList: true});
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
            replicationStatus = status;
            renderTargets(status);
            observeReplication();
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
