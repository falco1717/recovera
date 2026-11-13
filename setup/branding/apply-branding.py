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

# Web UI layout prefix. Images up to 5.6.x keep templates and assets under
# commonlookandfeel/ (plus a vintage/ copy of some templates); 5.12.x is flat.
# Set by main() from the installed tree; "" means the flat layout.
LAYOUT = ""


def detect_layout(root: "Path | None" = None) -> str:
    root = ROOT if root is None else root
    # A stock 5.6.x template, not just the directory: Recovera files left in a
    # commonlookandfeel/ tree on a flat image must not switch the layout.
    return "commonlookandfeel/" if (root / "templates/commonlookandfeel/Default/layout.base.html.twig").is_file() else ""


def asset(relative: str) -> str:
    """Path of a web asset, as used by Twig asset() and under /datto/web."""
    return LAYOUT + relative


def script_tag(relative: str) -> str:
    return f"<script type=\"text/javascript\" src=\"{{{{ asset('{asset(relative)}') }}}}\"></script>"


def template_paths(relative: str, *, vintage: bool = False) -> list[Path]:
    paths = [ROOT / "templates" / (LAYOUT + relative)]
    if vintage and LAYOUT:
        paths.append(ROOT / "templates/vintage" / relative)
    return paths


def remove_stray_legacy_files() -> list[str]:
    """On a flat (5.12.x) tree, remove commonlookandfeel/ trees that contain only
    Recovera files (left behind by a 5.6.x branding run on this image)."""
    removed = []
    for base in (ROOT / "templates/commonlookandfeel", WEB / "commonlookandfeel"):
        if not base.is_dir():
            continue
        files = [path for path in base.rglob("*") if path.is_file() or path.is_symlink()]
        if files and all("recovera" in str(path.relative_to(base)).lower() for path in files):
            shutil.rmtree(base)
            removed.append(str(base))
    return removed


def localize(text: str) -> str:
    """Adapt a flat-layout resource (Twig template, controller) to this image."""
    if not LAYOUT:
        return text
    text = text.replace("{% extends 'Default/", "{% extends '" + LAYOUT + "Default/")
    text = text.replace("asset('js/", "asset('" + LAYOUT + "js/")
    return text.replace("render('Configure/", "render('" + LAYOUT + "Configure/")

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
    css = "/" + asset("UI/css/recovera-brand.css")
    css_link = f"{css}?v={CSS_VERSION}"
    device_settings = "/" + asset("js/App/Configure/RecoveraDeviceSettings.js")
    # Replace any existing recovera-brand.css link (any version) with the
    # current cache-busted one; inject it if it is not present yet.
    text, replaced = re.subn(
        r'<link rel="stylesheet" href="/(?:commonlookandfeel/)?UI/css/recovera-brand\.css(?:\?v=[^"]*)?" />',
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
        "path('offsite_configure')",
        'path("offsite_configure")',
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
        script = "    " + script_tag("js/App/Configure/OffsiteSync/RecoveraOffsiteApiClient.js") + "\n"
        text = text.replace(needle, needle + script, 1)
    if "recovera-offsite-csrf" not in text:
        text = text.replace("{% block content %}", "{% block content %}\n    <div id=\"recovera-offsite-csrf\" class=\"d-none\">{{ csrfTag() }}</div>", 1)
    return text


def patch_offsite_javascript(text: str) -> str:
    return text.replace("}(Datto.API.Client, jQuery,", "}(Datto.App.RecoveraOffsiteApiClient, jQuery,")


BROKEN_RECOVERY_POINTS_TAG = re.compile(
    r'<script type=\\"text/javascript\\" src=\\"'
    r"(\{\{ asset\('[^']*RecoveraRecoveryPoints\.js'\) \}\})"
    r'\\"></script>'
)


def patch_recovery_points_template(text: str) -> str:
    # Releases up to 0.6.37 wrote this tag with literal backslashes before its
    # quotes, so browsers never ran the script. Repair it in place.
    text = BROKEN_RECOVERY_POINTS_TAG.sub(r'<script type="text/javascript" src="\1"></script>', text)
    if "RecoveraRecoveryPoints.js" not in text:
        pattern = re.compile(
            r'(?P<script><script[^>]+RecoveryPointsView\.js[^>]*></script>)'
        )
        addition = script_tag("js/App/Assets/RecoveraRecoveryPoints.js")
        text = pattern.sub(lambda match: match.group("script") + "\n" + addition, text, count=1)
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
        needle = "    " + script_tag("js/App/Agents/WizardSystem.js") + "\n"
        script = "    " + script_tag("js/App/Agents/RecoveraProtectSystem.js") + "\n"
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


SYNCHRONIZE_PANEL = '<div id="recovera-sync-panel" class="recovera-sync-panel"></div>'


def patch_synchronize_template(text: str) -> str:
    """Show Recovera appliance replication on the native Synchronize page."""
    if "RecoveraSynchronize.js" not in text:
        synchronize_script = script_tag("js/App/Synchronize/RecoveraSynchronize.js")
        pattern = re.compile(r"(?P<script><script[^>]+Synchronize/ReplicationStatusView\.js[^>]*></script>)")
        patched, count = pattern.subn(lambda match: match.group("script") + "\n    " + synchronize_script,
                                      text, count=1)
        if not count:
            start = text.find("{% block scripts %}")
            end = text.find("{% endblock %}", start) if start >= 0 else -1
            if end >= 0:
                patched = text[:end] + "    " + synchronize_script + "\n" + text[end:]
        text = patched
    if 'id="recovera-sync-panel"' not in text:
        body = '<div id="synchronizeBody">'
        if body in text:
            text = text.replace(body, body + "\n        " + SYNCHRONIZE_PANEL, 1)
        elif "{% block content %}" in text:
            text = text.replace("{% block content %}",
                                "{% block content %}\n    " + SYNCHRONIZE_PANEL, 1)
    return text




def patch_network_status_template(text: str) -> str:
    """Replace Datto's vendor-endpoint connectivity check with Recovera's."""
    if "RecoveraNetworkCheck.js" in text:
        return text
    pattern = re.compile(r"(?P<script><script[^>]+Configure/Network/ConnectivityView\.js[^>]*></script>)")
    addition = script_tag("js/App/Configure/Network/RecoveraNetworkCheck.js")
    return pattern.sub(lambda match: match.group("script") + "\n" + addition, text, count=1)


def patch_home_device_info(text: str) -> str:
    if "RecoveraHome.js" not in text:
        text = text.replace(
            "{% set numOffsiteTargets = deviceInfo.offsiteTargets|length %}",
            "{% set numOffsiteTargets = deviceInfo.offsiteTargets|length %}\n"
            + script_tag("js/App/Home/RecoveraHome.js"),
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
    global LAYOUT
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-branding.py LOGO_PNG")
    logo_source = Path(sys.argv[1])
    if not logo_source.is_file():
        raise SystemExit(f"logo not found: {logo_source}")
    LAYOUT = detect_layout()
    if not LAYOUT:
        for path in remove_stray_legacy_files():
            print(f"removed stray 5.6.x-layout Recovera files: {path}")

    logo_target = WEB / "UI/img/recovera-logo.png"
    css_target = WEB / asset("UI/css/recovera-brand.css")
    logo_target.parent.mkdir(parents=True, exist_ok=True)
    css_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(logo_source, logo_target)
    shutil.copy2(Path(__file__).with_name("recovera-brand.css"), css_target)
    resources = Path(__file__).parent
    controller = ROOT / "src/App/Controller/Web/Configure/RecoveraTargetController.php"
    templates = ROOT / "templates" / LAYOUT
    scripts = WEB / asset("js/App")
    for source, target in (
        (resources / "RecoveraTargetController.php", controller),
        (resources / "recovera-target.html.twig", templates / "Configure/RecoveraTarget/index.html.twig"),
        (resources / "RecoveraTarget.js", scripts / "Configure/RecoveraTarget.js"),
        (resources / "recovera-access.html.twig", templates / "Configure/RecoveraAccess/index.html.twig"),
        (resources / "RecoveraAccess.js", scripts / "Configure/RecoveraAccess.js"),
        (resources / "RecoveraOffsiteApiClient.js", scripts / "Configure/OffsiteSync/RecoveraOffsiteApiClient.js"),
        (resources / "RecoveraRecoveryPoints.js", scripts / "Assets/RecoveraRecoveryPoints.js"),
        (resources / "RecoveraProtectSystem.js", scripts / "Agents/RecoveraProtectSystem.js"),
        (resources / "RecoveraHome.js", scripts / "Home/RecoveraHome.js"),
        (resources / "RecoveraDeviceSettings.js", scripts / "Configure/RecoveraDeviceSettings.js"),
        (resources / "RecoveraSynchronize.js", scripts / "Synchronize/RecoveraSynchronize.js"),
        (resources / "RecoveraNetworkCheck.js", scripts / "Configure/Network/RecoveraNetworkCheck.js"),
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix in (".twig", ".php"):
            target.write_text(localize(source.read_text(encoding="utf-8")), encoding="utf-8")
            shutil.copymode(source, target)
        else:
            shutil.copy2(source, target)
    legacy_redirect = WEB / "configure/offsite/index.php"
    if legacy_redirect.is_file() and "Recovera Peer Replication" in legacy_redirect.read_text(encoding="utf-8"):
        legacy_redirect.unlink()
        with contextlib.suppress(OSError):
            legacy_redirect.parent.rmdir()

    for path in template_paths("Default/layout.base.html.twig", vintage=True):
        update(path, add_global_branding)
    for relative in ("Default/desktop.menu.html.twig", "Default/mobile.menu.html.twig"):
        for path in template_paths(relative):
            update(path, replace_nav_logo)
            update(path, add_target_menu)

    for path in template_paths("Default/menu.html.twig"):
        update(path, add_target_visibility)
    for path in template_paths("Configure/OffsiteSync/index.html.twig"):
        update(path, patch_offsite_template)
    update(WEB / asset("js/App/Configure/OffsiteSync/OffsiteSyncSettingsView.js"), patch_offsite_javascript)
    for path in template_paths("Assets/RecoveryPoints/index.html.twig", vintage=True):
        update(path, patch_recovery_points_template)
    for path in template_paths("Agents/Add/index.html.twig"):
        update(path, patch_protect_system_index)
    for path in template_paths("Assets/Configure/cloud.backup.html.twig"):
        update(path, patch_replication_pane)
    for path in template_paths("Home/deviceInfo.block.html.twig"):
        update(path, patch_home_device_info)
    for path in template_paths("Synchronize/index.html.twig", vintage=True):
        update(path, patch_synchronize_template)
    for path in template_paths("Configure/Network/ip.status.html.twig", vintage=True):
        update(path, patch_network_status_template)
    update(ROOT / "config/routes.yaml", add_routes)

    for path in template_paths("Authentication/index.login.html.twig"):
        update(path, brand_login)
    for path in template_paths("Default/layout.wizard.three.html.twig"):
        update(path, brand_wizard)

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
