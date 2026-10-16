(function () {
    'use strict';
    let password = '';
    const byId = id => document.getElementById(id);
    function message(value, ok) {
        const box = byId('ra-message');
        box.className = 'alert ' + (ok ? 'alert-success' : 'alert-danger');
        box.textContent = value;
    }
    async function copyText(value) {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            try {
                await navigator.clipboard.writeText(value);
                return true;
            } catch (error) {
                // Self-signed appliance certificates can make Clipboard unavailable.
            }
        }
        const field = document.createElement('textarea');
        field.value = value;
        field.setAttribute('readonly', '');
        field.setAttribute('aria-hidden', 'true');
        field.style.position = 'fixed';
        field.style.left = '-9999px';
        field.style.top = '0';
        field.style.fontSize = '16px';
        document.body.appendChild(field);
        field.focus({preventScroll: true});
        field.select();
        field.setSelectionRange(0, value.length);
        let copied = false;
        try { copied = document.execCommand('copy'); }
        finally {
            field.value = '';
            field.remove();
        }
        return copied;
    }
    function selectDisplayedPassword() {
        const selection = window.getSelection();
        if (!selection) return;
        const range = document.createRange();
        range.selectNodeContents(byId('ra-password'));
        selection.removeAllRanges();
        selection.addRange(range);
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
            try {
                if (!password || !await copyText(password)) throw new Error('copy unavailable');
                message('Password copied.', true);
            } catch (error) {
                selectDisplayedPassword();
                message('Automatic copy is unavailable; the password is selected for manual copy.', false);
            }
        };
    });
}());
