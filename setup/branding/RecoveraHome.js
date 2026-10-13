(function () {
    'use strict';

    function renderTargets() {
        var cell = document.getElementById('recovera-offsite-servers');
        if (!cell) {
            return;
        }
        fetch('/api/recovera/offsite-target/status', {
            credentials: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        }).then(function (response) {
            if (!response.ok) {
                throw new Error(response.statusText);
            }
            return response.json();
        }).then(function (status) {
            var targets = Object.keys(status.peers || {}).filter(function (id) {
                return status.peers[id].enabled !== false;
            }).map(function (id) {
                var peer = status.peers[id];
                return peer.name + (peer.host ? ' (' + peer.host + ')' : '');
            });
            cell.textContent = targets.length ? targets.join(', ') : 'None';
            cell.title = targets.join('\n');
        }).catch(function () {
            // Leave the native value in place if this user cannot read the
            // Recovera replication status endpoint.
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', renderTargets);
    } else {
        renderTargets();
    }
}());
