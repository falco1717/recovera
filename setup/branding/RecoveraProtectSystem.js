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

    function installWizardBridge() {
        if (!Datto.App.WizardSystem || Datto.App.WizardSystem.prototype.recoveraInstalled) {
            return;
        }
        var prototype = Datto.App.WizardSystem.prototype;
        var nativeAddSystems = prototype.addSystems;
        prototype.recoveraInstalled = true;
        prototype.addSystems = function (systems, doneCallback, statusCallback) {
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
        // The native "no targets" message lives inside #replicationTargetSelect,
        // which toggleSelect(false) hides — so when no peer is paired the user
        // sees a blank area instead of an explanation. This visible note sits
        // OUTSIDE that collapsed container and explains the empty state.
        function ensureTargetNote(self) {
            if (self.$recoveraTargetNote && self.$recoveraTargetNote.length) {
                return;
            }
            self.$recoveraTargetNote = $('<div class="pt-2 recovera-target-note" style="color:#b00020;">')
                .text('No target Recovera appliance is paired yet. Pair one under ' +
                      'Configure → Off-site Target, then reopen this wizard.')
                .hide();
            if (self.$replicationTargetSelect && self.$replicationTargetSelect.length) {
                self.$replicationTargetSelect.before(self.$recoveraTargetNote);
            }
        }
        prototype.getAuthorizedDevices = function () {
            var self = this;
            ensureTargetNote(self);
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
                    // No peer paired: default to No Replication and keep the view
                    // clean; the note is shown when the user actively picks Target
                    // (click handler in render), matching native SIRIS behavior.
                    self.$replicationTypeCloud.prop('checked', true);
                    self.$replicationTypeSiris.prop('checked', false);
                    self.toggleSelect(false);
                    if (self.$recoveraTargetNote) { self.$recoveraTargetNote.hide(); }
                    return;
                }
                if (self.$recoveraTargetNote) { self.$recoveraTargetNote.hide(); }
                if ($('input[name=replicationType]:checked').val() === 'siris') {
                    self.toggleSelect(true);
                }
            }).catch(function (error) {
                self.recoveraHasPeers = false;
                self.$replicationTypeCloud.prop('checked', true);
                self.$replicationTypeSiris.prop('checked', false);
                self.toggleSelect(false);
                if (self.$recoveraTargetNote) {
                    self.$recoveraTargetNote
                        .text('Could not reach the Recovera replication service: ' + error.message)
                        .show();
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
            ensureTargetNote(self);
            // Surface the empty-state reason the moment the user chooses Target.
            self.$replicationTypeSiris.on('click', function () {
                if (!self.recoveraHasPeers && self.$recoveraTargetNote) {
                    self.$recoveraTargetNote.show();
                }
            });
            self.$replicationTypeCloud.on('click', function () {
                if (self.$recoveraTargetNote) { self.$recoveraTargetNote.hide(); }
            });
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
