(function ($) {
    'use strict';

    var endpoint = '/api/recovera/offsite-target/';

    function csrf() {
        var input = document.querySelector('#recovera-protect-csrf input[name="csrf"]');
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
                interval_minutes: seconds <= 0 ? 5 : Math.max(5, Math.ceil(seconds / 60)),
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
        prototype.getAuthorizedDevices = function () {
            var self = this;
            request('status', 'GET').then(function (status) {
                var peers = Object.keys(status.peers || {}).filter(function (id) {
                    return status.peers[id].enabled !== false;
                });
                self.$replicationTargetSelectInput.empty();
                peers.forEach(function (id) {
                    var peer = status.peers[id];
                    $('<option>').val(id).text(peer.name + ' — ' + peer.host)
                        .appendTo(self.$replicationTargetSelectInput);
                });
                if (peers.length === 0) {
                    self.$replicationTypeCloud.prop('checked', true);
                    self.$replicationTypeSiris.prop('checked', false);
                    self.toggleSelect(false);
                    self.$replicationTargetInfoBoxError
                        .text('Pair a target appliance under Configure → Off-site Target first.').show();
                    return;
                }
                self.$replicationTargetInfoBoxError.hide();
                if ($('input[name=replicationType]:checked').val() === 'siris') {
                    self.toggleSelect(true);
                }
            }).catch(function (error) {
                self.$replicationTypeCloud.prop('checked', true);
                self.$replicationTypeSiris.prop('checked', false);
                self.toggleSelect(false);
                self.$replicationTargetInfoBoxError.text(error.message).show();
            });
        };
        prototype.render = function () {
            var result = nativeRender.apply(this, arguments);
            $('label[for="replicationTypeSiris"]').text('Target Recovera appliance');
            $('label[for="replicationTargetSelectInput"]').text('Select authorized target appliance');
            $('label[for="standardCloudBackupIntervalSelect"]').text('Replicate backups to the target appliance');
            $('#standardCloudRetention label').first().text('Keep backups on the target appliance for');
            return result;
        };
    }

    installWizardBridge();
    $(function () {
        installWizardBridge();
        installTargetBridge();
    });
}(jQuery));
