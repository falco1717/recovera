#!/usr/bin/env python3
"""Apply Recovera branding without renaming compatibility-critical packages."""

from __future__ import annotations

import contextlib
import re
import shutil
import sys
from pathlib import Path


ROOT = Path("/usr/lib/datto/device")
WEB = Path("/datto/web")


def update(path: Path, transform) -> bool:
    if not path.is_file():
        return False
    original = path.read_text(encoding="utf-8")
    changed = transform(original)
    if changed == original:
        return False
    path.write_text(changed, encoding="utf-8")
    return True


def add_global_branding(text: str) -> str:
    marker = "/commonlookandfeel/UI/css/recovera-brand.css"
    if marker in text:
        return text
    needle = "</head>"
    tag = f'    <link rel="stylesheet" href="{marker}" />\n'
    return text.replace(needle, tag + needle, 1)


def replace_nav_logo(text: str) -> str:
    if "recovera-brand" in text:
        return text
    pattern = re.compile(r'<img class="navbar-brand px-4 py-0 me-5"[^>]*datto-navbar-logo\.svg[^>]*/>')
    replacement = (
        '<a class="recovera-brand navbar-brand px-4 py-0 me-5" href="/">'
        '<img src="/UI/img/recovera-logo.png" alt="Recovera">'
        '<span>Recovera</span></a>'
    )
    return pattern.sub(replacement, text, count=1)


def brand_login(text: str) -> str:
    if "recovera-login-brand" in text:
        return text
    old = '<h3 class="font-18">{{ loginTo }} {{ base.deviceName }}</h3>'
    new = (
        '<div class="recovera-login-brand">'
        '<img src="/UI/img/recovera-logo.png" alt="">'
        '<span>Recovera</span></div>\n'
        '                <h3 class="font-18">Sign in to Recovera</h3>\n'
        '                <div class="recovera-device-name">{{ base.deviceName }}</div>'
    )
    return text.replace(old, new, 1)


def brand_wizard(text: str) -> str:
    if "recovera-wizard-brand" in text:
        return text
    needle = '<div class="wizard-header">'
    replacement = (
        needle + '\n                <div class="recovera-wizard-brand">'
        '<img src="/UI/img/recovera-logo.png" alt="">'
        '<span>Recovera</span></div>'
    )
    return text.replace(needle, replacement, 1)


def brand_translation(text: str) -> str:
    text = re.sub(r"\bDatto\b", "Recovera", text)
    text = re.sub(
        r'^app\.title:.*$',
        'app.title: "Recovera - %deviceName%"',
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r'^registration\.register\.title:.*$',
        'registration.register.title: "Set Up Recovera"',
        text,
        flags=re.MULTILINE,
    )
    return text


def add_target_visibility(text: str) -> str:
    needle = "{% set showConfigureOffsiteSync = feature.isSupported('FEATURE_OFFSITE') and is_granted('PERMISSION_OFFSITE_WRITE') %}"
    addition = needle + "\n{% set showRecoveraTarget = is_granted('PERMISSION_OFFSITE_WRITE') %}"
    return text if "showRecoveraTarget" in text else text.replace(needle, addition, 1)


def add_target_menu(text: str) -> str:
    text = text.replace(
        "if showConfigureNetworking or showConfigureOffsiteSync or showConfigureDeviceSettings",
        "if showConfigureNetworking or showConfigureOffsiteSync or showRecoveraTarget or showConfigureDeviceSettings",
    )
    if "path('recovera_target')" in text:
        return text
    end = "                            {% endif %}\n"
    anchor = "{{ \"menu.configure.offsite\"|trans }}"
    position = text.find(anchor)
    if position < 0:
        return text
    position = text.find(end, position)
    if position < 0:
        return text
    position += len(end)
    mobile = "ps-5 py-1 pe-0" in text
    classes = ' class="dropdown-item ps-5 py-1 pe-0"' if mobile else ' class="dropdown-item"'
    block = (
        "                            {% if showRecoveraTarget %}\n"
        "                                <li>\n"
        f"                                    <a{classes} href=\"{{{{ path('recovera_target') }}}}\">\n"
        "                                        Off-site Target\n"
        "                                    </a>\n"
        "                                </li>\n"
        "                            {% endif %}\n"
    )
    return text[:position] + block + text[position:]


def patch_offsite_template(text: str) -> str:
    marker = "RecoveraOffsiteApiClient.js"
    if marker not in text:
        needle = "{% block scripts %}\n"
        script = "    <script type=\"text/javascript\" src=\"{{ asset('commonlookandfeel/js/App/Configure/OffsiteSync/RecoveraOffsiteApiClient.js') }}\"></script>\n"
        text = text.replace(needle, needle + script, 1)
    if "recovera-offsite-csrf" not in text:
        text = text.replace("{% block content %}", "{% block content %}\n    <div id=\"recovera-offsite-csrf\" class=\"d-none\">{{ csrfTag() }}</div>", 1)
    return text


def patch_offsite_javascript(text: str) -> str:
    return text.replace("}(Datto.API.Client, jQuery,", "}(Datto.App.RecoveraOffsiteApiClient, jQuery,")


def add_routes(text: str) -> str:
    text = text.replace(
        "path: /configure/offsite-target/api/{operation}",
        "path: /api/recovera/offsite-target/{operation}",
    )
    if "recovera_target:" in text:
        return text
    return text.rstrip() + """

recovera_target:
    path: /configure/offsite-target
    defaults: { _controller: 'Datto\\App\\Controller\\Web\\Configure\\RecoveraTargetController::indexAction' }

recovera_target_api:
    path: /api/recovera/offsite-target/{operation}
    defaults: { _controller: 'Datto\\App\\Controller\\Web\\Configure\\RecoveraTargetController::apiAction' }
"""


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-branding.py LOGO_PNG")
    logo_source = Path(sys.argv[1])
    if not logo_source.is_file():
        raise SystemExit(f"logo not found: {logo_source}")

    logo_target = WEB / "UI/img/recovera-logo.png"
    css_target = WEB / "commonlookandfeel/UI/css/recovera-brand.css"
    logo_target.parent.mkdir(parents=True, exist_ok=True)
    css_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(logo_source, logo_target)
    shutil.copy2(Path(__file__).with_name("recovera-brand.css"), css_target)
    resources = Path(__file__).parent
    controller = ROOT / "src/App/Controller/Web/Configure/RecoveraTargetController.php"
    target_template = ROOT / "templates/commonlookandfeel/Configure/RecoveraTarget/index.html.twig"
    target_js = WEB / "commonlookandfeel/js/App/Configure/RecoveraTarget.js"
    offsite_js = WEB / "commonlookandfeel/js/App/Configure/OffsiteSync/RecoveraOffsiteApiClient.js"
    for source, target in (
        (resources / "RecoveraTargetController.php", controller),
        (resources / "recovera-target.html.twig", target_template),
        (resources / "RecoveraTarget.js", target_js),
        (resources / "RecoveraOffsiteApiClient.js", offsite_js),
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    legacy_redirect = WEB / "configure/offsite/index.php"
    if legacy_redirect.is_file() and "Recovera Peer Replication" in legacy_redirect.read_text(encoding="utf-8"):
        legacy_redirect.unlink()
        with contextlib.suppress(OSError):
            legacy_redirect.parent.rmdir()

    for path in (
        ROOT / "templates/commonlookandfeel/Default/layout.base.html.twig",
        ROOT / "templates/vintage/Default/layout.base.html.twig",
    ):
        update(path, add_global_branding)
    for relative in (
        "templates/commonlookandfeel/Default/desktop.menu.html.twig",
        "templates/commonlookandfeel/Default/mobile.menu.html.twig",
    ):
        path = ROOT / relative
        update(path, replace_nav_logo)
        update(path, add_target_menu)

    update(ROOT / "templates/commonlookandfeel/Default/menu.html.twig", add_target_visibility)
    update(ROOT / "templates/commonlookandfeel/Configure/OffsiteSync/index.html.twig", patch_offsite_template)
    update(WEB / "commonlookandfeel/js/App/Configure/OffsiteSync/OffsiteSyncSettingsView.js", patch_offsite_javascript)
    update(ROOT / "config/routes.yaml", add_routes)

    update(ROOT / "templates/commonlookandfeel/Authentication/index.login.html.twig", brand_login)
    update(ROOT / "templates/commonlookandfeel/Default/layout.wizard.three.html.twig", brand_wizard)

    for path in (ROOT / "translations").glob("*messages.en_US.yml"):
        update(path, brand_translation)
    update(WEB / "js/translations/en_US.js", brand_translation)

    for cache in (
        Path("/var/cache/datto/device/prod/twig"),
        Path("/var/cache/datto/device/prod/translations"),
        Path("/var/cache/datto/device/prod"),
    ):
        if cache.is_dir():
            shutil.rmtree(cache)

    print("Recovera branding applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
