(function () {
    'use strict';
    function addRow(card, label, value) {
        if (card.querySelector('[data-recovera-row="' + label + '"]')) return;
        var table = card.querySelector('table');
        if (!table) return;
        var tr = document.createElement('tr'); tr.dataset.recoveraRow = label;
        var th = document.createElement('th'); th.textContent = label;
        var td = document.createElement('td'); td.textContent = value;
        tr.append(th, td); (table.tBodies[0] || table).appendChild(tr);
    }
    function badge(card, value) {
        if (card.querySelector('.recovera-replication-badge')) return;
        var heading = card.querySelector('h2,h3,h4,.card-title');
        if (!heading) return;
        var item = document.createElement('span');
        item.className = 'recovera-replication-badge badge bg-info ms-2';
        item.textContent = value; heading.appendChild(item);
    }
    function render(status) {
        document.querySelectorAll('[data-agent]').forEach(function (card) {
            var key = card.getAttribute('data-agent');
            var rule = (status.rules || {})[key];
            var local = (status.local_assets || []).find(function (item) { return item.key === key; });
            if (rule) {
                var target = (status.peers || {})[rule.peer_id] || {};
                var transfer = ((status.state || {}).assets || {})[rule.peer_id + ':' + key] || {};
                badge(card, 'Replicating');
                addRow(card, 'Replication destination', target.name || target.host || rule.peer_id);
                addRow(card, 'Last replication', transfer.last_snapshot || 'Waiting for first transfer');
                addRow(card, 'Replication health', transfer.error || transfer.mode || 'Scheduled');
            } else if (local && local.replicated) {
                badge(card, 'Replicated');
                addRow(card, 'Replication source', (local.origin || {}).sourceApplianceName || (local.origin || {}).sourceApplianceId || 'Paired source');
                addRow(card, 'Recovery readiness', local.snapshots.length ? 'Ready' : 'No recovery points');
            }
        });
    }
    function load() {
        fetch('/api/recovera/offsite-target/status', {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}})
            .then(function (response) { return response.ok ? response.json() : Promise.reject(new Error(response.statusText)); })
            .then(render).catch(function () {});
    }
    document.addEventListener('DOMContentLoaded', function () {
        load(); window.setTimeout(load, 1500); window.setTimeout(load, 5000);
    });
}());
