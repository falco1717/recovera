#!/usr/bin/env python3
"""Apply Recovera branding without renaming compatibility-critical packages."""

from __future__ import annotations

import contextlib
import hashlib
import re
import shutil
import sys
from pathlib import Path


ROOT = Path("/usr/lib/datto/device")
WEB = Path("/datto/web")

# Cache-bust the branding stylesheet so updated CSS reaches browsers that
# already cached the previous copy (phones in particular).
BRAND_CSS_SOURCE = Path(__file__).with_name("recovera-brand.css")
CSS_VERSION = (
    hashlib.sha1(BRAND_CSS_SOURCE.read_bytes()).hexdigest()[:10]
    if BRAND_CSS_SOURCE.is_file()
    else "1"
)


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
    css = "/commonlookandfeel/UI/css/recovera-brand.css"
    css_link = f"{css}?v={CSS_VERSION}"
    device_settings = "/commonlookandfeel/js/App/Configure/RecoveraDeviceSettings.js"
    # Replace any existing recovera-brand.css link (any version) with the
    # current cache-busted one; inject it if it is not present yet.
    text, replaced = re.subn(
        r'<link rel="stylesheet" href="/commonlookandfeel/UI/css/recovera-brand\.css(?:\?v=[^"]*)?" />',
        f'<link rel="stylesheet" href="{css_link}" />',
        text,
    )
    additions = ""
    if replaced == 0:
        additions += f'    <link rel="stylesheet" href="{css_link}" />\n'
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
    if not additions:
        return text
    if needle in text:
        return text.replace(needle, needle + "\n" + "\n".join(additions), 1)
    # Image releases occasionally rearrange the stock visibility declarations.
    # Defining our flags at the start of the shared menu context is safe and avoids
    # silently losing the Recovera links when that exact stock line changes.
    return "\n".join(additions) + "\n" + text


def _menu_item_end(text: str, anchor_position: int) -> int:
    """Return a safe insertion point immediately after a stock menu item."""
    position = text.find("</li>", anchor_position)
    if position < 0:
        return -1
    position += len("</li>")
    trailing = re.match(r"(?P<space>\s*)(?P<endif>{%\s*endif\s*%})?", text[position:])
    if trailing:
        position += trailing.end()
    return position


def add_target_menu(text: str) -> str:
    # Keep the Configure dropdown visible even on images where its stock entries
    # are all disabled. Match the condition by the variables it contains instead
    # of depending on exact whitespace or ordering from one image release.
    configure_if = re.compile(r"({%\s*if\s+)([^%\n]+)(\s*%})")

    def include_recovera(match: re.Match) -> str:
        condition = match.group(2).strip()
        stock_flags = (
            "showConfigureNetworking",
            "showConfigureOffsiteSync",
            "showConfigureDeviceSettings",
        )
        if sum(flag in condition for flag in stock_flags) < 2:
            return match.group(0)
        for flag in ("showRecoveraTarget", "showRecoveraAccess"):
            if flag not in condition:
                condition += f" or {flag}"
        return f"{match.group(1)}{condition}{match.group(3)}"

    text = configure_if.sub(include_recovera, text)

    # Prefer the native Off-site Sync entry so the Recovera additions sit beside
    # the related setting. Fall back to another Configure item, and finally the
    # Configure dropdown itself, for image versions that omit Off-site Sync.
    position = -1
    for anchor in (
        "menu.configure.offsite",
        "path('configure_offsite')",
        'path("configure_offsite")',
        "menu.configure.device",
        "path('configure_device')",
        'path("configure_device")',
    ):
        anchor_position = text.find(anchor)
        if anchor_position >= 0:
            position = _menu_item_end(text, anchor_position)
            if position >= 0:
                break
    if position < 0:
        configure_position = text.find("menu.configure")
        submenu_position = text.find("<ul", configure_position)
        position = text.find("</ul>", submenu_position)
        if configure_position < 0 or submenu_position < 0 or position < 0:
            return text
    mobile = "ps-5 py-1 pe-0" in text
    classes = ' class="dropdown-item ps-5 py-1 pe-0"' if mobile else ' class="dropdown-item"'
    indent = "                            "
    block = ""
    if "path('recovera_target')" not in text:
        block += (
            f"\n{indent}{{% if showRecoveraTarget %}}\n"
            f"{indent}    <li>\n"
            f"{indent}        <a{classes} href=\"{{{{ path('recovera_target') }}}}\">\n"
            f"{indent}            Off-site Target\n"
            f"{indent}        </a>\n"
            f"{indent}    </li>\n"
            f"{indent}{{% endif %}}"
        )
    if "path('recovera_access')" not in text:
        block += (
            f"\n{indent}{{% if showRecoveraAccess %}}\n"
            f"{indent}    <li>\n"
            f"{indent}        <a{classes} href=\"{{{{ path('recovera_access') }}}}\">\n"
            f"{indent}            Appliance Access\n"
            f"{indent}        </a>\n"
            f"{indent}    </li>\n"
            f"{indent}{{% endif %}}"
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
