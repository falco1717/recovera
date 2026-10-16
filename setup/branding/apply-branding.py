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
    needle = "</head>"
    additions = ""
    css = "/commonlookandfeel/UI/css/recovera-brand.css"
    device_settings = "/commonlookandfeel/js/App/Configure/RecoveraDeviceSettings.js"
    if css not in text:
        additions += f'    <link rel="stylesheet" href="{css}" />\n'
    if device_settings not in text:
        additions += f'    <script defer src="{device_settings}"></script>\n'
    return text.replace(needle, additions + needle, 1) if additions else text


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
    text = text.replace("Authorized Target SIRIS", "Authorized Recovera Target")
    text = text.replace("Target SIRIS", "Target Recovera appliance")
    text = text.replace("your SIRIS", "your Recovera target")
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
    additions = []
    if "showRecoveraTarget" not in text:
        additions.append("{% set showRecoveraTarget = is_granted('PERMISSION_OFFSITE_WRITE') %}")
    if "showRecoveraAccess" not in text:
        additions.append("{% set showRecoveraAccess = is_granted('PERMISSION_OFFSITE_WRITE') %}")
    return text.replace(needle, needle + "\n" + "\n".join(additions), 1) if additions else text


def add_target_menu(text: str) -> str:
    text = text.replace(
        "if showConfigureNetworking or showConfigureOffsiteSync or showConfigureDeviceSettings",
        "if showConfigureNetworking or showConfigureOffsiteSync or showRecoveraTarget or showRecoveraAccess or showConfigureDeviceSettings",
    )
    text = text.replace(
        "if showConfigureNetworking or showConfigureOffsiteSync or showRecoveraTarget or showConfigureDeviceSettings",
        "if showConfigureNetworking or showConfigureOffsiteSync or showRecoveraTarget or showRecoveraAccess or showConfigureDeviceSettings",
    )
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
    block = ""
    if "path('recovera_target')" not in text:
        block += (
            "                            {% if showRecoveraTarget %}\n"
            "                                <li>\n"
            f"                                    <a{classes} href=\"{{{{ path('recovera_target') }}}}\">\n"
            "                                        Off-site Target\n"
            "                                    </a>\n"
            "                                </li>\n"
            "                            {% endif %}\n"
        )
    if "path('recovera_access')" not in text:
        block += (
            "                            {% if showRecoveraAccess %}\n"
            "                                <li>\n"
            f"                                    <a{classes} href=\"{{{{ path('recovera_access') }}}}\">\n"
            "                                        Appliance Access\n"
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


def patch_recovery_points_template(text: str) -> str:
    if "RecoveraRecoveryPoints.js" not in text:
        pattern = re.compile(
            r'(?P<script><script[^>]+RecoveryPointsView\.js[^>]*></script>)'
        )
        text = pattern.sub(
            r"\g<script>\n<script type=\"text/javascript\" src=\"{{ asset('commonlookandfeel/js/App/Assets/RecoveraRecoveryPoints.js') }}\"></script>",
            text,
            count=1,
        )
    if "recovera-recovery-points-csrf" not in text:
        text = text.replace(
            "{% block content %}",
            "{% block content %}\n    <div id=\"recovera-recovery-points-csrf\" class=\"d-none\">{{ csrfTag() }}</div>",
            1,
        )
    return text


def patch_protect_system_index(text: str) -> str:
    text = text.replace("feature.isSupported('FEATURE_PEER_REPLICATION')", "true")
    text = text.replace(
        "canOffsite: {{ canOffsite|json_encode|raw }}",
        "canOffsite: true",
    )
    if "RecoveraProtectSystem.js" not in text:
        needle = "    <script type=\"text/javascript\" src=\"{{ asset('commonlookandfeel/js/App/Agents/WizardSystem.js') }}\"></script>\n"
        script = "    <script type=\"text/javascript\" src=\"{{ asset('commonlookandfeel/js/App/Agents/RecoveraProtectSystem.js') }}\"></script>\n"
        text = text.replace(needle, needle + script, 1)
    if "recovera-protect-csrf" not in text:
        text = text.replace(
            "{% block agentsFinish %}",
            "{% block agentsFinish %}\n    <div id=\"recovera-protect-csrf\" class=\"d-none\">{{ csrfTag() }}</div>",
            1,
        )
    return text


def patch_replication_pane(text: str) -> str:
    if "inWizard or feature.isSupported('FEATURE_PEER_REPLICATION')" not in text:
        text = text.replace(
            "feature.isSupported('FEATURE_PEER_REPLICATION')",
            "(inWizard or feature.isSupported('FEATURE_PEER_REPLICATION'))",
        )
    if "inWizard or feature.isSupported('FEATURE_OFFSITE')" not in text:
        text = text.replace(
            "feature.isSupported('FEATURE_OFFSITE')",
            "(inWizard or feature.isSupported('FEATURE_OFFSITE'))",
            1,
        )
    return text


def patch_home_device_info(text: str) -> str:
    if "RecoveraHome.js" not in text:
        text = text.replace(
            "{% set numOffsiteTargets = deviceInfo.offsiteTargets|length %}",
            "{% set numOffsiteTargets = deviceInfo.offsiteTargets|length %}\n"
            "<script type=\"text/javascript\" src=\"{{ asset('commonlookandfeel/js/App/Home/RecoveraHome.js') }}\"></script>",
            1,
        )
    if 'id="recovera-offsite-servers"' not in text:
        marker = """                <td class=\"label-dark w-33\">
                    {% if numOffsiteTargets == 0 %}"""
        replacement = """                <td id=\"recovera-offsite-servers\" class=\"label-dark w-33\">
                    {% if numOffsiteTargets == 0 %}"""
        text = text.replace(marker, replacement, 1)
    return text


def add_routes(text: str) -> str:
    text = text.replace(
        "path: /configure/offsite-target/api/{operation}",
        "path: /api/recovera/offsite-target/{operation}",
    )
    additions = ""
    if "recovera_target:" not in text:
        additions += """

recovera_target:
    path: /configure/offsite-target
    defaults: { _controller: 'Datto\\App\\Controller\\Web\\Configure\\RecoveraTargetController::indexAction' }

recovera_target_api:
    path: /api/recovera/offsite-target/{operation}
    defaults: { _controller: 'Datto\\App\\Controller\\Web\\Configure\\RecoveraTargetController::apiAction' }
"""
    if "recovera_access:" not in text:
        additions += """

recovera_access:
    path: /configure/appliance-access
    defaults: { _controller: 'Datto\\App\\Controller\\Web\\Configure\\RecoveraTargetController::accessAction' }
"""
    return text.rstrip() + additions if additions else text


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
    access_template = ROOT / "templates/commonlookandfeel/Configure/RecoveraAccess/index.html.twig"
    access_js = WEB / "commonlookandfeel/js/App/Configure/RecoveraAccess.js"
    offsite_js = WEB / "commonlookandfeel/js/App/Configure/OffsiteSync/RecoveraOffsiteApiClient.js"
    recovery_points_js = WEB / "commonlookandfeel/js/App/Assets/RecoveraRecoveryPoints.js"
    protect_system_js = WEB / "commonlookandfeel/js/App/Agents/RecoveraProtectSystem.js"
    home_js = WEB / "commonlookandfeel/js/App/Home/RecoveraHome.js"
    device_settings_js = WEB / "commonlookandfeel/js/App/Configure/RecoveraDeviceSettings.js"
    for source, target in (
        (resources / "RecoveraTargetController.php", controller),
        (resources / "recovera-target.html.twig", target_template),
        (resources / "RecoveraTarget.js", target_js),
        (resources / "recovera-access.html.twig", access_template),
        (resources / "RecoveraAccess.js", access_js),
        (resources / "RecoveraOffsiteApiClient.js", offsite_js),
        (resources / "RecoveraRecoveryPoints.js", recovery_points_js),
        (resources / "RecoveraProtectSystem.js", protect_system_js),
        (resources / "RecoveraHome.js", home_js),
        (resources / "RecoveraDeviceSettings.js", device_settings_js),
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
    for path in (
        ROOT / "templates/commonlookandfeel/Assets/RecoveryPoints/index.html.twig",
        ROOT / "templates/vintage/Assets/RecoveryPoints/index.html.twig",
    ):
        update(path, patch_recovery_points_template)
    update(ROOT / "templates/commonlookandfeel/Agents/Add/index.html.twig", patch_protect_system_index)
    update(ROOT / "templates/commonlookandfeel/Assets/Configure/cloud.backup.html.twig", patch_replication_pane)
    update(ROOT / "templates/commonlookandfeel/Home/deviceInfo.block.html.twig", patch_home_device_info)
    update(ROOT / "config/routes.yaml", add_routes)

    update(ROOT / "templates/commonlookandfeel/Authentication/index.login.html.twig", brand_login)
    update(ROOT / "templates/commonlookandfeel/Default/layout.wizard.three.html.twig", brand_wizard)

    for path in (ROOT / "translations").glob("*messages.en_US.yml"):
        update(path, brand_translation)
    update(WEB / "js/translations/en_US.js", brand_translation)

    cache = Path("/var/cache/datto/device/prod")
    if cache.is_dir():
        # PHP-FPM can recreate cache entries while this cleanup is running.
        # A best-effort removal is sufficient because the process is restarted
        # immediately after branding is applied.
        shutil.rmtree(cache, ignore_errors=True)

    print("Recovera branding applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
