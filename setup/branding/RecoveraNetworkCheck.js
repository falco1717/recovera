(function () {
    'use strict';

    // Datto's outbound connectivity check probes vendor endpoints (heartbeat,
    // off-site cloud, speedtest and update servers) that an offline Recovera
    // appliance must not contact. Replace it with Recovera's own check of the
    // gateway, MTU, DNS, time sync, update source and paired appliances.
    var settings = window.Datto && Datto.App && Datto.App.Network && Datto.App.Network.Settings;
    var View = settings && settings.ConnectivityView;
    if (!View || !View.prototype) {
        return;
    }
    var endpoint = '/api/recovera/offsite-target/';

    function get(operation) {
        return fetch(endpoint + operation, {
            credentials: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        }).then(function (response) {
            return response.json().then(function (body) {
                if (!response.ok) {
                    throw body;
                }
                return body;
            });
        });
    }

    function removeVendorHelp() {
        var links = document.querySelectorAll('#buConnectivity a[href*="datto.com"], a[href*="help.datto.com"]');
        Array.prototype.forEach.call(links, function (link) {
            var box = link.closest('div');
            if (box && !box.querySelector('#connectivityStatus')) {
                box.remove();
            } else {
                link.remove();
            }
        });
    }

    function addDetails(view, result) {
        var details = result.details || {};
        var cells = view.$connectivityStatusTable.find('td');
        cells.each(function () {
            var cell = this;
            Object.keys(details).forEach(function (label) {
                if (cell.textContent.indexOf(label) !== -1) {
                    cell.title = details[label];
                }
            });
        });
    }

    function notify(view, kind, text) {
        // The vintage view takes (id, type, message); the current one
        // takes (type, element, data).
        if (view.notificationField) {
            view.fireNotification(view.notificationField, kind === 'busy' ? 'info' : kind, text);
        } else if (kind === 'busy') {
            view.fireNotification('busy', 'spinner', {'message': {'text': text}});
        } else {
            view.fireNotification(kind, 'toast', {'message': {'text': text}, 'templateId': view.toastTemplate});
        }
    }

    function show(view, result) {
        view.refreshTable({created: result.created, data: result.data || {}});
        addDetails(view, result);
        removeVendorHelp();
    }

    function prompt(view) {
        var tbody = view.$connectivityStatusTable.children('tbody').first();
        tbody.empty();
        var row = document.createElement('tr');
        var cell = document.createElement('td');
        cell.textContent = 'Run the check to test this appliance\'s gateway, DNS, time sync, ' +
            'update source and paired Recovera appliances.';
        row.appendChild(cell);
        tbody.append(row);
        view.$connectivityStatusTableHeader.text('Connectivity Status');
    }

    View.prototype.renderView = function () {
        var self = this;
        removeVendorHelp();
        // The page renders Datto's last result server-side; show Recovera's instead.
        get('network-check-last').then(function (result) {
            if (result && result.data && Object.keys(result.data).length) {
                show(self, result);
            } else {
                prompt(self);
            }
        }).catch(function () {
            prompt(self);
        });

        this.$runConnectivityCheckButton.off('click').on('click', function () {
            notify(self, 'busy', self.context.translations['notification.connectivityCheckStarted']);
            self.$runConnectivityCheckButton.prop('disabled', true);
            get('network-check').then(function (result) {
                show(self, result);
                notify(self, 'success', self.context.translations['notification.connectivityCheckComplete']);
                self.$runConnectivityCheckButton.prop('disabled', false);
            }).catch(function () {
                self.displayCheckFailure();
            });
        });
    };
}());
