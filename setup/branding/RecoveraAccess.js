(function () {
    'use strict';
    let password = '';
    const byId = id => document.getElementById(id);
    function message(value, ok) {
        const box = byId('ra-message');
        box.className = 'alert ' + (ok ? 'alert-success' : 'alert-danger');
        box.textContent = value;
    }
    document.addEventListener('DOMContentLoaded', () => {
        byId('ra-reveal').onclick = async () => {
            try {
                const root = byId('recovera-access').dataset.api;
                const response = await fetch(root + 'backup-admin-credential', {
                    credentials: 'same-origin',
                    headers: {'X-Requested-With': 'XMLHttpRequest'}
                });
                const value = await response.json();
                if (!response.ok) throw new Error(value.error || response.statusText);
                password = value.password;
                byId('ra-password').textContent = password;
                byId('ra-reveal').textContent = 'Hide password';
                byId('ra-copy').classList.remove('d-none');
                byId('ra-reveal').onclick = () => window.location.reload();
            } catch (error) { message(error.message, false); }
        };
        byId('ra-copy').onclick = async () => {
            try { await navigator.clipboard.writeText(password); message('Password copied.', true); }
            catch (error) { message('Copy failed; select the displayed password manually.', false); }
        };
    });
}());
