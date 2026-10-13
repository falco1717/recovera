(function () {
    'use strict';
    let current = null;
    let discovered = null;
    const byId = id => document.getElementById(id);
    const text = (node, value) => { node.textContent = value == null ? '—' : String(value); };
    function option(value, label) { const item = document.createElement('option'); item.value = value; text(item, label); return item; }
    function duration(hours) { if (Number(hours) >= 240000) return 'Forever'; if (hours % 8760 === 0) return (hours / 8760) + ' year(s)'; if (hours % 744 === 0) return (hours / 744) + ' month(s)'; if (hours % 168 === 0) return (hours / 168) + ' week(s)'; return hours + ' hours'; }
    function bytes(value) { const n = Number(value || 0); if (!n) return '—'; const units = ['B','KB','MB','GB','TB']; const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024))); return (n / Math.pow(1024, i)).toFixed(i ? 1 : 0) + ' ' + units[i]; }
    function when(value) { return value ? new Date(Number(value) * 1000).toLocaleString() : 'Never'; }
    function row(values) { const tr = document.createElement('tr'); values.forEach(v => { const td = document.createElement('td'); text(td, v); tr.appendChild(td); }); return tr; }
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
            const assets = byId('rt-asset'); assets.replaceChildren(...current.local_assets.filter(x => !x.replicated).map(x => option(x.key, (x.name || x.key) + ' (' + x.snapshots.length + ' recovery points)')));
            const peers = byId('rt-peer'); peers.replaceChildren(...Object.entries(current.peers).map(([id, x]) => option(id, x.name + ' — ' + x.host)));
            const rows = [];
            Object.entries(current.rules).forEach(([asset, rule]) => { const state = current.state.assets[rule.peer_id + ':' + asset] || {}; const local = current.local_assets.find(item => item.key === asset); const schedule = rule.schedule_mode === 'every_backup' ? 'Every backup' : (rule.schedule_mode === 'daily' ? 'Every day' : rule.interval_minutes + ' minutes'); rows.push(row([local?.name || asset, current.peers[rule.peer_id]?.name || rule.peer_id, schedule, rule.priority || 'normal', duration(rule.retention_hours || 240000), state.last_snapshot || '—', state.error || state.mode || 'Waiting'])); });
            byId('rt-status').replaceChildren(...rows); text(byId('rt-events'), JSON.stringify((current.state.events || []).slice(-20).reverse(), null, 2));
            const applianceRows = [row([current.appliance.name, 'This appliance', 'Local', bytes(current.storage.free) + ' free', 'Now', current.storage.health || 'Unknown'])];
            Object.entries(current.peers || {}).forEach(([id, peer]) => { const health = (current.peer_health || {})[id] || {}; applianceRows.push(row([peer.name || id, 'Target', peer.host, bytes(health.storage && health.storage.free) + ' free', when(health.last_contact), health.error || health.status || 'Paired'])); });
            Object.entries(current.sources || {}).forEach(([id, source]) => applianceRows.push(row([source.name || id, 'Source', source.address || '—', '—', when(source.paired_at), 'Authorized'])));
            byId('rt-appliances').replaceChildren(...applianceRows);
            byId('rt-received').replaceChildren(...(current.received_assets || []).map(item => row([item.name || item.key, item.origin?.sourceApplianceName || item.origin?.sourceApplianceId || 'Paired source', item.snapshots.length, item.latest_snapshot || '—', item.recovery_ready ? 'Ready for recovery' : item.recovery_issues.join('; ')])));
        } catch (error) { message(error.message, false); }
    }
    document.addEventListener('DOMContentLoaded', () => {
        byId('rt-code').onclick = async () => { try { const value = await api('pairing-code', {}); text(byId('rt-code-output'), 'Code: ' + value.code + '\nExpires: ' + new Date(value.expires * 1000).toLocaleString() + '\nTLS fingerprint: ' + current.tls_fingerprint); } catch (e) { message(e.message, false); } };
        byId('rt-discover').onclick = async () => { try { discovered = await api('discover', {host: byId('rt-host').value, port: 443}); text(byId('rt-discovery'), JSON.stringify(discovered, null, 2)); message('Compare the fingerprint with the target before pairing.', true); } catch (e) { message(e.message, false); } };
        byId('rt-pair').onclick = async () => { try { if (!discovered) throw new Error('Discover the target first.'); await api('peer', {host: byId('rt-host').value, port: 443, code: byId('rt-pair-code').value, fingerprint: discovered.observed_fingerprint, appliance_id: discovered.appliance_id}); message('Target paired.', true); await load(); } catch (e) { message(e.message, false); } };
        byId('rt-save').onclick = async () => { try { await api('rule', {asset: byId('rt-asset').value, peer_id: byId('rt-peer').value, schedule_mode: byId('rt-mode').value, interval_minutes: Number(byId('rt-interval').value), priority: byId('rt-priority').value, retention_hours: Number(byId('rt-retention').value)}); message('Replication policy saved.', true); await load(); } catch (e) { message(e.message, false); } };
        byId('rt-sync').onclick = async () => { try { message('Synchronization is running…', true); const result = await api('sync', {}); message('Synchronization complete: ' + JSON.stringify(result.results), true); await load(); } catch (e) { message(e.message, false); } };
        load(); window.setInterval(load, 30000);
    });
}());
