var Datto = Datto || {};
Datto.App = Datto.App || {};
Datto.App.RecoveraOffsiteApiClient = function () {
    this.call = function (method, params, success, failure) {
        var operations = {
            'v1/device/offsite/syncSchedule/add': 'schedule-add',
            'v1/device/offsite/syncSchedule/getWeeklyAveragesAndSchedules': 'offsite',
            'v1/device/offsite/syncSchedule/getWeeklyAverages': 'offsite',
            'v1/device/offsite/syncSchedule/delete': 'schedule-delete',
            'v1/device/system/calculateMaximumUploadSpeed': 'speed-test',
            'v1/device/settings/setOffsiteSyncSpeed': 'speed-set',
            'v1/device/offsite/maintenance/setMaxConcurrentSyncs': 'concurrency-set'
        };
        var operation = operations[method];
        if (!operation) { failure({error: {message: 'Unsupported Recovera operation'}}); return; }
        var csrf = document.querySelector('#recovera-offsite-csrf input[name="csrf"]');
        var post = operation === 'offsite' ? undefined : new URLSearchParams({csrf: csrf.value, payload: JSON.stringify(params || {})});
        fetch('/api/recovera/offsite-target/' + operation, {method: operation === 'offsite' ? 'GET' : 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest'}, body: post})
            .then(function (response) { return response.json().then(function (body) { if (!response.ok) throw body; return body; }); })
            .then(function (body) { success(method === 'v1/device/offsite/syncSchedule/getWeeklyAverages' ? body.averages : body); })
            .catch(function (error) { failure(error.error ? error : {error: {message: error.error || error.message || 'Request failed'}}); });
    };
};
