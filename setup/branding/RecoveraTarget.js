(function () {
    'use strict';
    let current = null;
    let discovered = null;
    const byId = id => document.getElementById(id);
    const text = (node, value) => { node.textContent = value == null ? '—' : String(value); };
    function option(value, label) { const item = document.createElement('option'); item.value = value; text(item, label); return item; }
    async function api(operation, body) {
        const root = byId('recovera-target').dataset.api;
        const csrf = document.querySelector('#recovera-csrf input[name="csrf"]');
        const post = body === undefined ? undefined : new URLSearchParams({csrf: csrf.value, payload: JSON.stringify(body)});
        const response = await fetch(root + operation, {method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest'}, body: post});
        const value = await response.json();
        if (!response.ok) throw new Error(value.error || response.statusText);
        return value;
    }
    function message(value, ok) { const box = byId('rt-message'); box.className = 'alert ' + (ok ? 'alert-success' : 'alert-danger'); text(box, value); }
    async function load() {
        try {
            current = await api('status');
            text(byId('rt-name'), current.appliance.name); text(byId('rt-fingerprint'), current.tls_fingerprint);
            const assets = byId('rt-asset'); assets.replaceChildren(...current.local_assets.filter(x => !x.replicated).map(x => option(x.key, x.key + ' (' + x.snapshots.length + ' recovery points)')));
            const peers = byId('rt-peer'); peers.replaceChildren(...Object.entries(current.peers).map(([id, x]) => option(id, x.name + ' — ' + x.host)));
            const rows = [];
            Object.entries(current.rules).forEach(([asset, rule]) => { const state = current.state.assets[rule.peer_id + ':' + asset] || {}; const tr = document.createElement('tr'); [asset, current.peers[rule.peer_id]?.name || rule.peer_id, state.last_snapshot || '—', state.error || state.mode || 'Waiting'].forEach(v => { const td = document.createElement('td'); text(td, v); tr.appendChild(td); }); rows.push(tr); });
            byId('rt-status').replaceChildren(...rows); text(byId('rt-events'), JSON.stringify((current.state.events || []).slice(-20).reverse(), null, 2));
        } catch (error) { message(error.message, false); }
    }
    document.addEventListener('DOMContentLoaded', () => {
        byId('rt-code').onclick = async () => { try { const value = await api('pairing-code', {}); text(byId('rt-code-output'), 'Code: ' + value.code + '\nExpires: ' + new Date(value.expires * 1000).toLocaleString() + '\nTLS fingerprint: ' + current.tls_fingerprint); } catch (e) { message(e.message, false); } };
        byId('rt-discover').onclick = async () => { try { discovered = await api('discover', {host: byId('rt-host').value, port: Number(byId('rt-port').value)}); text(byId('rt-discovery'), JSON.stringify(discovered, null, 2)); message('Compare the fingerprint with the target before pairing.', true); } catch (e) { message(e.message, false); } };
        byId('rt-pair').onclick = async () => { try { if (!discovered) throw new Error('Discover the target first.'); await api('peer', {host: byId('rt-host').value, port: Number(byId('rt-port').value), code: byId('rt-pair-code').value, fingerprint: discovered.observed_fingerprint, appliance_id: discovered.appliance_id}); message('Target paired.', true); await load(); } catch (e) { message(e.message, false); } };
        byId('rt-save').onclick = async () => { try { await api('rule', {asset: byId('rt-asset').value, peer_id: byId('rt-peer').value, interval_minutes: Number(byId('rt-interval').value)}); message('Replication policy saved.', true); await load(); } catch (e) { message(e.message, false); } };
        byId('rt-sync').onclick = async () => { try { message('Synchronization is running…', true); const result = await api('sync', {}); message('Synchronization complete: ' + JSON.stringify(result.results), true); await load(); } catch (e) { message(e.message, false); } };
        load(); window.setInterval(load, 30000);
    });
}());
