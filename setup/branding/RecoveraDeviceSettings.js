(function () {
    'use strict';

    const RELAY_TITLES = new Set([
        'datto relay forced login',
        'recovera relay forced login'
    ]);

    function normalizedText(element) {
        return (element.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
    }

    function sectionFor(title) {
        const direct = title.closest('.card, .panel, fieldset');
        if (direct) {
            return direct;
        }

        // Older device templates use plain nested divs instead of Bootstrap cards.
        // Stop before an ancestor that also contains the following Reboot section.
        let section = title.parentElement;
        while (section && section.parentElement) {
            const parentText = normalizedText(section.parentElement);
            if (parentText.includes('reboot now') || parentText.includes('schedule a reboot')) {
                break;
            }
            section = section.parentElement;
        }
        return section;
    }

    function removeLegacyRelayControl() {
        if (!/^\/configure\/device\/?$/.test(window.location.pathname)) {
            return;
        }

        document.querySelectorAll('h1, h2, h3, h4, h5, h6, legend, .card-title').forEach(function (title) {
            if (!RELAY_TITLES.has(normalizedText(title))) {
                return;
            }
            const section = sectionFor(title);
            if (section) {
                section.remove();
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', removeLegacyRelayControl, {once: true});
    } else {
        removeLegacyRelayControl();
    }
}());
