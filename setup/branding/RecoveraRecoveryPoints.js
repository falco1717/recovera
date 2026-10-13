(function () {
    'use strict';

    var endpoint = '/api/recovera/offsite-target/';
    var latest = {};

    function csrf() {
        var input = document.querySelector('#recovera-recovery-points-csrf input[name="csrf"]');
        return input ? input.value : '';
    }

    function request(operation, method, payload) {
        var options = {
            method: method,
            headers: {'X-Requested-With': 'XMLHttpRequest'},
            credentials: 'same-origin'
        };
        if (method === 'POST') {
            var form = new FormData();
            form.append('csrf', csrf());
            form.append('payload', JSON.stringify(payload || {}));
            options.body = form;
        }
        return fetch(endpoint + operation, options).then(function (response) {
            return response.json().then(function (body) {
                if (!response.ok) {
                    throw body;
                }
                return body;
            });
        });
    }

    function errorForNative(error) {
        var message = error && (error.error || error.message);
        if (message && message.message) {
            message = message.message;
        }
        return {error: {message: message || 'Could not queue the recovery point'}};
    }

    function cellFor(epoch) {
        var row = document.querySelector('.pointRow[data-epoch="' + epoch + '"]') ||
            document.querySelector('tr[data-epoch="' + epoch + '"]');
        return row ? {row: row, cell: row.querySelector('.existsOffsite')} : null;
    }

    function circle(classes, title) {
        var node = document.createElement('div');
        node.className = 'circle ' + classes;
        if (title) {
            node.title = title;
        }
        return node;
    }

    function applyItem(item) {
        var point = cellFor(String(item.snapshot));
        var target = item.target || item.peer_id || 'the paired target';
        if (!point || !point.cell) {
            return;
        }
        point.row.classList.remove('rowOffsite', 'rowOffsiting');
        point.cell.textContent = '';
        if (item.status === 'completed') {
            point.row.classList.add('rowOffsite');
            point.cell.appendChild(circle('circle-success', 'Replicated to ' + target));
        } else if (item.status === 'error') {
            point.cell.appendChild(circle('circle-action-needed queue-offsite', item.error || 'Replication failed'));
        } else {
            point.row.classList.add('rowOffsiting');
            point.cell.textContent = item.status === 'syncing' ? 'Streaming' : 'Queued';
            point.cell.title = item.status === 'syncing' ? 'Replicating to ' + target :
                'Queued for ' + target;
        }
    }

    function applyForAsset(assetKey) {
        (latest[assetKey] || []).forEach(applyItem);
    }

    function refresh(view) {
        request('queue-status', 'GET').then(function (body) {
            latest = {};
            (body.items || []).forEach(function (item) {
                (latest[item.asset] = latest[item.asset] || []).push(item);
            });
            applyForAsset(view.context.assetKey);
        }).catch(function () {
            // The native page remains usable when the peer service is unavailable.
        });
    }

    function install() {
        if (!window.Datto || !Datto.App || !Datto.App.Assets ||
                !Datto.App.Assets.RecoveryPointsView) {
            return;
        }
        var prototype = Datto.App.Assets.RecoveryPointsView.prototype;
        if (prototype.recoveraInstalled) {
            return;
        }
        prototype.recoveraInstalled = true;
        var nativeRender = prototype.render;
        prototype.render = function () {
            var view = this;
            if (!this.api.recoveraQueueInstalled) {
                var nativeCall = this.api.call.bind(this.api);
                this.api.call = function (method, params, success, failure) {
                    if (method !== 'v1/device/snapshot/send') {
                        return nativeCall(method, params, success, failure);
                    }
                    return request('queue', 'POST', params).then(function (body) {
                        if (success) {
                            success(body);
                        }
                    }).catch(function (error) {
                        if (failure) {
                            failure(errorForNative(error));
                        }
                    });
                };
                this.api.recoveraQueueInstalled = true;
            }
            var result = nativeRender.apply(this, arguments);
            window.setTimeout(function () { applyForAsset(view.context.assetKey); }, 0);
            if (!this.recoveraQueueTimer) {
                refresh(this);
                this.recoveraQueueTimer = window.setInterval(function () { refresh(view); }, 2000);
            }
            return result;
        };
    }

    install();
}());
