(function () {
    'use strict';

    // Recovera appliance-to-appliance replication runs outside the native
    // SpeedSync queue, so the stock Synchronize charts never show it. This
    // panel reports live and recent Recovera transfers alongside them.
    var endpoint = '/api/recovera/offsite-target/replication-activity';
    var pollMs = 5000;
    var timer = null;

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) {
            node.className = className;
        }
        if (text !== undefined && text !== null) {
            node.textContent = text;
        }
        return node;
    }

    function bytes(value) {
        var units = ['B', 'KB', 'MB', 'GB', 'TB'];
        var amount = Number(value) || 0;
        var unit = 0;
        while (amount >= 1000 && unit < units.length - 1) {
            amount /= 1000;
            unit += 1;
        }
        return (unit === 0 ? amount.toFixed(0) : amount.toFixed(amount >= 100 ? 0 : 1)) + ' ' + units[unit];
    }

    function duration(seconds) {
        seconds = Math.max(0, Math.round(Number(seconds) || 0));
        if (seconds < 90) {
            return seconds + ' sec';
        }
        var minutes = Math.round(seconds / 60);
        if (minutes < 90) {
            return minutes + ' min';
        }
        var hours = Math.floor(minutes / 60);
        if (hours < 48) {
            return hours + ' h ' + (minutes % 60) + ' min';
        }
        return Math.floor(hours / 24) + ' d ' + (hours % 24) + ' h';
    }

    function when(epoch) {
        var number = Number(epoch);
        if (!number) {
            return 'unknown';
        }
        return new Date(number * 1000).toLocaleString();
    }

    function ago(epoch) {
        var number = Number(epoch);
        if (!number) {
            return '';
        }
        return duration(Date.now() / 1000 - number) + ' ago';
    }

    function applianceLabel(name, address, fallback) {
        if (name && address && name !== address) {
            return name + ' (' + address + ')';
        }
        return name || address || fallback;
    }

    function modeLabel(mode) {
        mode = String(mode || '');
        if (mode === 'full') {
            return 'Full (initial seed)';
        }
        if (mode === 'resumed' || mode === 'resumable') {
            return 'Resumed transfer';
        }
        if (mode.indexOf('incremental') === 0) {
            return 'Incremental';
        }
        if (mode === 'already-present') {
            return 'Already on target';
        }
        return mode || 'Transfer';
    }

    function line(parent, label, value) {
        var row = el('div', 'recovera-sync-line');
        row.style.margin = '2px 0';
        var name = el('span', 'recovera-sync-label', label + ': ');
        name.style.color = '#6c757d';
        row.appendChild(name);
        row.appendChild(el('span', null, value));
        parent.appendChild(row);
    }

    function ensureStyles() {
        if (document.getElementById('recovera-sync-style')) {
            return;
        }
        var style = el('style');
        style.id = 'recovera-sync-style';
        style.textContent =
            '@keyframes recovera-sync-slide{0%{margin-left:-35%}100%{margin-left:100%}}' +
            '.recovera-sync-indeterminate{height:100%;width:35%;border-radius:5px;background:#2c7be5;' +
            'animation:recovera-sync-slide 1.6s ease-in-out infinite}' +
            '@media (prefers-reduced-motion:reduce){.recovera-sync-indeterminate{animation:none;' +
            'width:100%;opacity:.5}}';
        document.head.appendChild(style);
    }

    function progressBar(percent) {
        var track = el('div', 'recovera-sync-progress');
        track.style.cssText = 'height:10px;border-radius:5px;background:#e9ecef;overflow:hidden;margin:6px 0;';
        if (percent === null || percent === undefined) {
            // The total is unknown, but the transfer is moving: show activity.
            ensureStyles();
            track.appendChild(el('div', 'recovera-sync-indeterminate'));
            track.title = 'Transfer in progress; the total size is not known';
            return track;
        }
        var fill = el('div');
        fill.style.cssText = 'height:100%;width:' + Math.max(1, Math.min(100, percent)) + '%;background:#2c7be5;';
        track.appendChild(fill);
        return track;
    }

    function transferBlock(item, direction) {
        var block = el('div', 'recovera-sync-transfer');
        block.style.cssText = 'padding:10px 0;border-top:1px solid rgba(0,0,0,.08);';
        var interrupted = item.status === 'interrupted';
        var peer = direction === 'outbound'
            ? 'to ' + applianceLabel(item.peer_name, item.peer_address, 'paired target')
            : 'from ' + applianceLabel(item.source_name, item.source_address, 'paired source');
        var title = el('div', null, (direction === 'outbound' ? 'Sending ' : 'Receiving ') +
            (item.name || item.asset) + ' ' + peer);
        title.style.fontWeight = '600';
        block.appendChild(title);
        if (interrupted) {
            line(block, 'Status', direction === 'outbound'
                ? 'Interrupted; it resumes from where it stopped on the next scheduled replication'
                : 'Paused; waiting for the source appliance to resume the transfer');
        } else {
            block.appendChild(progressBar(item.percent));
            var amount = item.bytes_total
                ? bytes(item.bytes_done) + ' of ~' + bytes(item.bytes_total) +
                  (item.percent !== null && item.percent !== undefined ? ' (' + item.percent + '%)' : '')
                : bytes(item.bytes_done) + (direction === 'outbound' ? ' sent so far' : ' received so far') +
                  ' (total size not reported for this transfer)';
            line(block, 'Progress', amount);
            line(block, 'Speed', item.rate_bps ? bytes(item.rate_bps) + '/s' : 'measuring…');
            if (item.eta_seconds) {
                line(block, 'Time remaining', '~' + duration(item.eta_seconds));
            }
            if (item.started) {
                line(block, 'Running for', duration(Date.now() / 1000 - item.started));
            }
        }
        if (item.mode) {
            line(block, 'Type', modeLabel(item.mode));
        }
        if (item.codec) {
            line(block, 'In transit', 'compressed (' + item.codec + '); speed counts backup data');
        }
        if (item.snapshot) {
            line(block, 'Recovery point', when(item.snapshot));
        }
        return block;
    }

    function section(card, heading) {
        var title = el('h6', null, heading);
        title.style.cssText = 'margin:14px 0 4px;font-weight:600;';
        card.appendChild(title);
    }

    function render(container, data) {
        container.textContent = '';
        var card = el('div', 'card');
        var body = el('div', 'card-body');
        card.appendChild(body);
        var header = el('h5', 'card-title', 'Recovera appliance replication');
        header.style.marginBottom = '2px';
        body.appendChild(header);
        var note = el('div', null,
            'Appliance-to-appliance transfers. These do not appear in the SpeedSync charts on this page.');
        note.style.cssText = 'color:#6c757d;font-size:.9em;';
        body.appendChild(note);

        if (data.maintenance) {
            var hold = el('div', null, 'Replication is paused for maintenance (' +
                (data.maintenance.reason || 'maintenance') + ')' +
                (data.maintenance.since ? ' since ' + when(data.maintenance.since) : '') +
                '. Transfers resume from where they stopped when it ends.');
            hold.style.cssText = 'margin-top:8px;padding:8px 10px;border-radius:4px;' +
                'background:#fff3cd;color:#664d03;';
            body.appendChild(hold);
        }

        var active = data.active || {};
        var outbound = active.outbound || [];
        var inbound = active.inbound || [];
        section(body, 'Active transfers');
        if (!outbound.length && !inbound.length) {
            body.appendChild(el('div', null, 'No replication transfers are running right now.'));
        }
        outbound.forEach(function (item) { body.appendChild(transferBlock(item, 'outbound')); });
        inbound.forEach(function (item) { body.appendChild(transferBlock(item, 'inbound')); });

        var recentOut = data.recent_outbound || [];
        var recentIn = data.recent_inbound || [];
        if (recentOut.length || recentIn.length) {
            section(body, 'Last completed');
            recentOut.forEach(function (item) {
                var text = (item.name || item.asset) + ' → ' +
                    applianceLabel(item.peer_name, item.peer_address, 'target') + ': ';
                if (item.error) {
                    var failed = el('div', null, text + 'last attempt failed: ' + item.error);
                    failed.style.color = '#c0392b';
                    body.appendChild(failed);
                    return;
                }
                body.appendChild(el('div', null, text + (item.last_success
                    ? 'recovery point ' + when(item.last_snapshot) + ', finished ' + ago(item.last_success) +
                      ' (' + modeLabel(item.mode) + ')'
                    : 'no completed transfer yet')));
            });
            recentIn.forEach(function (item) {
                body.appendChild(el('div', null, (item.name || item.asset) + ' ← ' +
                    applianceLabel(item.source_name, item.source_address, 'source') +
                    ': recovery point ' + when(item.snapshot) +
                    ', received ' + ago(item.updated)));
            });
        }
        var paired = data.paired || {};
        if (!paired.targets && !paired.sources) {
            body.appendChild(el('div', null,
                'This appliance is not paired with another Recovera appliance. Use Configure → Off-site Target.'));
        }
        container.appendChild(card);
    }

    function showError(container, message) {
        container.textContent = '';
        var box = el('div', 'card');
        var body = el('div', 'card-body');
        body.appendChild(el('h5', 'card-title', 'Recovera appliance replication'));
        var text = el('div', null, message);
        text.style.color = '#c0392b';
        body.appendChild(text);
        box.appendChild(body);
        container.appendChild(box);
    }

    function poll(container) {
        if (document.hidden) {
            schedule(container);
            return;
        }
        fetch(endpoint, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}})
            .then(function (response) {
                return response.json().then(function (body) {
                    if (!response.ok) {
                        throw body;
                    }
                    return body;
                });
            })
            .then(function (data) { render(container, data); })
            .catch(function (error) {
                var message = error && (error.error || error.message);
                if (message && message.message) {
                    message = message.message;
                }
                showError(container, 'Replication status is unavailable' + (message ? ': ' + message : '.'));
            })
            .then(function () { schedule(container); });
    }

    function schedule(container) {
        if (timer) {
            clearTimeout(timer);
        }
        timer = setTimeout(function () { poll(container); }, pollMs);
    }

    function start() {
        var container = document.getElementById('recovera-sync-panel');
        if (!container) {
            return;
        }
        container.style.marginBottom = '16px';
        // Asset keys are 32-character words; let them wrap on phones.
        container.style.overflowWrap = 'anywhere';
        container.style.wordBreak = 'break-word';
        poll(container);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
}());
