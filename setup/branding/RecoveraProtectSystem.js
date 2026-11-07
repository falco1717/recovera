(function ($) {
    'use strict';

    var endpoint = '/api/recovera/offsite-target/';

    function csrf() {
        var input = document.querySelector('#recovera-protect-csrf input[name="csrf"], #recovera-asset-replication input[name="csrf"]');
        return input ? input.value : '';
    }

    function request(operation, method, payload) {
        var options = {
            method: method || 'GET',
            credentials: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        };
        if (options.method === 'POST') {
            var form = new URLSearchParams();
            form.set('csrf', csrf());
            form.set('payload', JSON.stringify(payload || {}));
            options.headers['Content-Type'] = 'application/x-www-form-urlencoded;charset=UTF-8';
            options.body = form;
        }
        return fetch(endpoint + operation, options).then(function (response) {
            return response.json().then(function (body) {
                if (!response.ok) {
                    throw new Error(body.error || response.statusText);
                }
                return body;
            });
        });
    }

    function selectedSystems(systems) {
        if (systems.type === 'agent') {
            return (systems.agentNames || []).map(function (name) { return {name: name}; });
        }
        return (systems.vms || []).map(function (vm) {
            var result = {};
            ['name', 'hostname', 'uuid', 'keyName'].forEach(function (key) {
                if (vm[key]) {
                    result[key] = vm[key];
                }
            });
            return result;
        });
    }

    function deduplicateSystems(systems) {
        var result = Object.assign({}, systems);
        var seen = new Set();
        if (systems.type === 'agent') {
            result.agentNames = (systems.agentNames || []).filter(function (name) {
                var identity = String(name || '').trim().toLowerCase();
                if (!identity || seen.has(identity)) return false;
                seen.add(identity);
                return true;
            });
        } else if (systems.type === 'agentless') {
            result.vms = (systems.vms || []).filter(function (vm, index) {
                var strong = String(vm.uuid || vm.keyName || '').trim().toLowerCase();
                var weak = [vm.name, vm.hostname].map(function (value) {
                    return String(value || '').trim().toLowerCase();
                }).filter(Boolean).join('|');
                var identity = strong ? 'id:' + strong : (weak ? 'name:' + weak : 'row:' + index);
                if (seen.has(identity)) return false;
                seen.add(identity);
                return true;
            });
        }
        return result;
    }

    function installWizardBridge() {
        if (!Datto.App.WizardSystem || Datto.App.WizardSystem.prototype.recoveraInstalled) {
            return;
        }
        var prototype = Datto.App.WizardSystem.prototype;
        var nativeAddSystems = prototype.addSystems;
        prototype.recoveraInstalled = true;
        prototype.addSystems = function (systems, doneCallback, statusCallback) {
            systems = deduplicateSystems(systems);
            var model = systems.model;
            if (!model || model.replicationType !== 'siris') {
                return nativeAddSystems.call(this, systems, doneCallback, statusCallback);
            }
            var seconds = Number(model.offsiteIntervalSeconds);
            var policy = {
                systems: selectedSystems(systems),
                peer_id: String(model.replicationTargetSiris),
                schedule_mode: seconds <= 0 ? 'every_backup' : (seconds === 86400 ? 'daily' : 'interval'),
                interval_minutes: seconds <= 0 ? 60 : Math.max(5, Math.ceil(seconds / 60)),
                priority: 'normal',
                retention_hours: Number(model.offsiteRetention && model.offsiteRetention.keep) || 240000
            };
            var original = {
                replicationType: model.replicationType,
                replicationTargetSiris: model.replicationTargetSiris,
                offsiteIntervalSeconds: model.offsiteIntervalSeconds
            };
            var finish = function (result) {
                if (!result.success) {
                    doneCallback(result);
                    return;
                }
                request('wizard-rule', 'POST', policy).then(function () {
                    doneCallback(result);
                }).catch(function (error) {
                    result.success = false;
                    result.message = 'The systems were protected, but Recovera could not save their replication policy: ' + error.message;
                    doneCallback(result);
                });
            };
            model.replicationType = 'none';
            model.replicationTargetSiris = 'noOffsite';
            model.offsiteIntervalSeconds = -1;
            try {
                return nativeAddSystems.call(this, systems, finish, statusCallback);
            } finally {
                model.replicationType = original.replicationType;
                model.replicationTargetSiris = original.replicationTargetSiris;
                model.offsiteIntervalSeconds = original.offsiteIntervalSeconds;
            }
        };
    }

    function installTargetBridge() {
        var settings = Datto.App.Assets && Datto.App.Assets.Settings;
        var View = settings && settings.ReplicationSettingsView;
        if (!View || View.prototype.recoveraInstalled) {
            return;
        }
        var prototype = View.prototype;
        var nativeRender = prototype.render;
        prototype.recoveraInstalled = true;
        // When no peer is paired, gray out the "Target Recovera appliance"
        // option entirely (so it reads as unavailable instead of showing a
        // blank area), and add an info (i) icon next to it that explains how to
        // set a target up. The native "no targets" message lives inside
        // #replicationTargetSelect, which toggleSelect(false) hides.
        var SETUP_HINT = 'To replicate off-site, first pair a target Recovera ' +
            'appliance: open <strong>Configure → Off-site Target</strong> and ' +
            'add one. It will then appear here to select.';
        function ensureTargetInfo(self) {
            if (self.$recoveraTargetInfo && self.$recoveraTargetInfo.length) {
                return;
            }
            var label = $('label[for="replicationTypeSiris"]');
            if (!label.length) { return; }
            self.$recoveraTargetInfo = $(
                '<span class="recovera-target-info ms-1" tabindex="0" role="img" ' +
                'aria-label="How to set up a target appliance" ' +
                'data-bs-toggle="tooltip" data-bs-placement="right" data-bs-html="true">' +
                '<i class="fa-regular fa-circle-info text-primary"></i></span>'
            ).attr('title', SETUP_HINT);
            label.after(self.$recoveraTargetInfo);
            try { self.$recoveraTargetInfo.tooltip(); } catch (e) {}
        }
        function setTargetEnabled(self, enabled) {
            self.$replicationTypeSiris.prop('disabled', !enabled);
            $('label[for="replicationTypeSiris"]').toggleClass('text-muted', !enabled);
            self.$replicationTypeSiris.closest('.form-check, span').css('opacity', enabled ? '' : '0.6');
        }
        prototype.getAuthorizedDevices = function () {
            var self = this;
            ensureTargetInfo(self);
            request('status', 'GET').then(function (status) {
                var peers = Object.keys(status.peers || {}).filter(function (id) {
                    return status.peers[id].enabled !== false;
                });
                self.recoveraHasPeers = peers.length > 0;
                self.$replicationTargetSelectInput.empty();
                peers.forEach(function (id) {
                    var peer = status.peers[id];
                    $('<option>').val(id).text(peer.name + (peer.host ? ' — ' + peer.host : ''))
                        .appendTo(self.$replicationTargetSelectInput);
                });
                if (peers.length === 0) {
                    // No peer paired: gray out and disable the Target option and
                    // keep No Replication selected. The (i) tooltip explains setup.
                    setTargetEnabled(self, false);
                    self.$replicationTypeCloud.prop('checked', true);
                    self.$replicationTypeSiris.prop('checked', false);
                    self.toggleSelect(false);
                    return;
                }
                setTargetEnabled(self, true);
                if ($('input[name=replicationType]:checked').val() === 'siris') {
                    self.toggleSelect(true);
                }
            }).catch(function (error) {
                // On error, keep No Replication selected and surface the reason
                // in the native error box rather than trapping on a dead option.
                self.recoveraHasPeers = false;
                setTargetEnabled(self, false);
                self.$replicationTypeCloud.prop('checked', true);
                self.$replicationTypeSiris.prop('checked', false);
                self.toggleSelect(false);
                if (self.$replicationTargetInfoBoxError) {
                    self.$replicationTargetInfoBoxError
                        .text('Could not reach the Recovera replication service: ' + error.message);
                }
            });
        };
        prototype.render = function () {
            var result = nativeRender.apply(this, arguments);
            var self = this;
            $('label[for="replicationTypeSiris"]').text('Target Recovera appliance');
            $('label[for="replicationTargetSelectInput"]').text('Select authorized target appliance');
            $('label[for="standardCloudBackupIntervalSelect"]').text('Replicate backups to the target appliance');
            $('#standardCloudRetention label').first().text('Keep backups on the target appliance for');
            ensureTargetInfo(self);
            return result;
        };
    }

    function option(value, label, selected) {
        return $('<option>').val(value).text(label).prop('selected', String(value) === String(selected));
    }

    function installAssetPolicyPanel() {
        var root = $('#recovera-asset-replication');
        if (!root.length || root.data('installed')) return;
        root.data('installed', true);
        var asset = String(root.data('asset'));
        request('status', 'GET').then(function (status) {
            var rule = (status.rules || {})[asset] || {};
            var box = $('<div class="row g-3">');
            var peer = $('<select class="form-select">');
            Object.keys(status.peers || {}).forEach(function (id) {
                peer.append(option(id, status.peers[id].name + ' — ' + status.peers[id].host, rule.peer_id));
            });
            var mode = $('<select class="form-select">')
                .append(option('every_backup', 'Every backup', rule.schedule_mode))
                .append(option('daily', 'Every day', rule.schedule_mode))
                .append(option('interval', 'Custom interval', rule.schedule_mode || 'interval'));
            var interval = $('<input class="form-control" type="number" min="5">').val(rule.interval_minutes || 60);
            var priority = $('<select class="form-select">')
                .append(option('high', 'High', rule.priority))
                .append(option('normal', 'Normal', rule.priority || 'normal'))
                .append(option('low', 'Low', rule.priority));
            var retention = $('<select class="form-select">');
            [[168,'1 week'],[336,'2 weeks'],[744,'1 month'],[2232,'3 months'],[4464,'6 months'],[8760,'1 year'],[240000,'Forever']].forEach(function (item) {
                retention.append(option(item[0], item[1], rule.retention_hours || 2232));
            });
            [['Target appliance',peer],['Schedule',mode],['Interval (minutes)',interval],['Priority',priority],['Target retention',retention]].forEach(function (item) {
                $('<div class="col-lg-4">').append($('<label class="form-label">').text(item[0]), item[1]).appendTo(box);
            });
            var enabled = $('<input type="checkbox" class="form-check-input me-2">').prop('checked', rule.enabled !== false);
            var save = $('<button type="button" class="btn btn-primary mt-3">').text('Save Recovera policy');
            var message = $('<span class="ms-3">');
            save.on('click', function () {
                save.prop('disabled', true); message.text('Saving…');
                request('rule', 'POST', {asset: asset, peer_id: peer.val(), schedule_mode: mode.val(), interval_minutes: Number(interval.val()), priority: priority.val(), retention_hours: Number(retention.val()), enabled: enabled.prop('checked')})
                    .then(function () { message.text('Policy saved.'); })
                    .catch(function (error) { message.text(error.message); })
                    .finally(function () { save.prop('disabled', false); });
            });
            $('#recovera-asset-policy').empty().append(box, $('<div class="form-check mt-3">').append(enabled, $('<label class="form-check-label">').text('Replication enabled')), save, message);
        }).catch(function (error) {
            $('#recovera-asset-policy').text(error.message);
        });
    }

    installWizardBridge();
    $(function () {
        installWizardBridge();
        installTargetBridge();
        installAssetPolicyPanel();
    });
}(jQuery));
