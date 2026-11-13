import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "setup" / "branding" / "apply-branding.py"
PEER_UI = Path(__file__).parents[1] / "setup" / "branding" / "apply-peer-ui.py"
ROOT = Path(__file__).parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("recovera_branding_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecoveraBrandingTests(unittest.TestCase):
    def test_global_assets_include_device_settings_cleanup_once(self):
        branding = load_module()
        source = "<html><head></head><body></body></html>"
        patched = branding.add_global_branding(source)

        self.assertIn("recovera-brand.css", patched)
        self.assertIn("RecoveraDeviceSettings.js", patched)
        self.assertEqual(branding.add_global_branding(patched), patched)

        cleanup = (ROOT / "setup" / "branding" / "RecoveraDeviceSettings.js").read_text()
        self.assertIn("recovera relay forced login", cleanup)
        self.assertIn(r"configure\/device", cleanup)
        self.assertIn("Update Now", cleanup)
        self.assertIn("settingUpgradeChannel", cleanup)
        self.assertIn("settingUpdateWindow", cleanup)
        self.assertIn("settingRecoveraUpdateNow", cleanup)
        self.assertIn("update-policy", cleanup)
        self.assertIn("update-install", cleanup)
        self.assertIn("input[name=\"csrf\"]", cleanup)
        self.assertIn("recovera.upgrade.available", cleanup)
        self.assertIn("globalAlertTemplate", cleanup)
        self.assertIn("updater.state.available", cleanup)
        self.assertIn("releaseIsNewer(release.version, value.installed_version)", cleanup)
        self.assertIn("AGENT_PAIR_EMPTY_REPLY", cleanup)
        self.assertIn("agent rejected this appliance\\'s certificate", cleanup)
        self.assertIn("already paired with another Recovera appliance", cleanup)
        self.assertIn("An agent can be protected by only one appliance", cleanup)
        self.assertIn("Configure → Off-site Target", cleanup)
        self.assertIn("MutationObserver", cleanup)
        self.assertIn("Expand Backup Storage", cleanup)
        self.assertIn("settingRecoveraStorageExpand", cleanup)
        self.assertIn("integrityCheckTimeoutNtfsresize", cleanup)
        self.assertIn("storage-status", cleanup)
        self.assertIn("storage-expand", cleanup)
        self.assertIn("expand-to-maximum", cleanup)

        home = (ROOT / "setup" / "branding" / "RecoveraHome.js").read_text()
        self.assertIn("replication-success", home)
        self.assertIn("last_success", home)
        self.assertIn("recoveraLastSynced", home)
        self.assertIn("MutationObserver", home)
        self.assertIn("replicationStatusTable", home)
        self.assertIn("tbody tr[data-asset]", home)

    def test_console_and_login_branding_are_recovera_owned(self):
        logo = (ROOT / "setup" / "branding" / "recovera-ascii.logo").read_text()
        motd = (ROOT / "setup" / "branding" / "recovera-motd").read_text()
        installer = (ROOT / "setup" / "setup.sh").read_text()

        self.assertNotIn("Datto", logo)
        self.assertIn("R E C O V E R A", motd)
        self.assertIn("/usr/lib/datto/statusshell/logo/0.logo", installer)
        self.assertIn("chmod a-x /etc/update-motd.d/25-datto", installer)
        self.assertIn("/etc/update-motd.d/25-recovera", installer)

        peer = (ROOT / "setup" / "peer" / "recovera-peer").read_text()
        package_builder = (ROOT / "tools" / "build-recovera-appliance-deb.sh").read_text()
        self.assertIn("RECOVERA_VERSION_PATH", peer)
        self.assertIn('"$ROOT/VERSION" "$stage/usr/local/share/recovera/VERSION"', package_builder)

    def test_recovery_points_bridge_is_injected_once_after_native_view(self):
        branding = load_module()
        source = """{% block scripts %}
<script src=\"{{ asset('js/App/Assets/RecoveryPointsView.js') }}\"></script>
{% endblock %}
{% block content %}<main></main>{% endblock %}
"""
        patched = branding.patch_recovery_points_template(source)
        self.assertIn("RecoveraRecoveryPoints.js", patched)
        self.assertIn("recovera-recovery-points-csrf", patched)
        self.assertLess(patched.index("RecoveryPointsView.js"),
                        patched.index("RecoveraRecoveryPoints.js"))
        self.assertEqual(branding.patch_recovery_points_template(patched), patched)
        self.assertIn('<script type="text/javascript" src="{{ asset(\'js/App/Assets/RecoveraRecoveryPoints.js\') }}"></script>',
                      patched)

    def test_recovery_points_repairs_the_backslash_quoted_tag(self):
        # Exactly what 0.6.37 and earlier left in the 5.6.3 template.
        branding = load_module()
        broken = ("<script src=\"{{ asset('commonlookandfeel/js/App/Assets/RecoveryPointsView.js') }}\"></script>\n"
                  "<script type=\\\"text/javascript\\\" src=\\\"{{ asset('commonlookandfeel/js/App/Assets/"
                  "RecoveraRecoveryPoints.js') }}\\\"></script>\n"
                  "{% block content %}\n    <div id=\"recovera-recovery-points-csrf\" class=\"d-none\"></div>")
        self.assertIn('type=\\"text/javascript\\"', broken)
        repaired = branding.patch_recovery_points_template(broken)
        self.assertNotIn("\\", repaired)
        self.assertIn('<script type="text/javascript" src="{{ asset(\'commonlookandfeel/js/App/Assets/'
                      'RecoveraRecoveryPoints.js\') }}"></script>', repaired)
        self.assertEqual(repaired.count("RecoveraRecoveryPoints.js"), 1)
        self.assertEqual(branding.patch_recovery_points_template(repaired), repaired)

    def test_protect_system_enables_recovera_replication_bridge_once(self):
        branding = load_module()
        source = """{% set cloudPaneTitle = feature.isSupported('FEATURE_PEER_REPLICATION') %}
{% block wizard_assets %}
    <script type=\"text/javascript\" src=\"{{ asset('js/App/Agents/WizardSystem.js') }}\"></script>
{% endblock %}
{% block agentsFinish %}
canOffsite: {{ canOffsite|json_encode|raw }}
{% endblock %}
"""
        patched = branding.patch_protect_system_index(source)
        self.assertIn("RecoveraProtectSystem.js", patched)
        self.assertIn("recovera-protect-csrf", patched)
        self.assertIn("canOffsite: true", patched)
        self.assertNotIn("FEATURE_PEER_REPLICATION", patched)
        self.assertEqual(branding.patch_protect_system_index(patched), patched)
        bridge = (ROOT / "setup" / "branding" / "RecoveraProtectSystem.js").read_text()
        self.assertIn("function deduplicateSystems(systems)", bridge)
        self.assertIn("systems = deduplicateSystems(systems)", bridge)

    def test_replication_pane_is_enabled_only_for_wizard_without_nesting(self):
        branding = load_module()
        source = """{% if feature.isSupported('FEATURE_PEER_REPLICATION') %}
{% if feature.isSupported('FEATURE_OFFSITE') %}{% endif %}
{% if feature.isSupported('FEATURE_PEER_REPLICATION') %}{% endif %}
{% endif %}"""
        patched = branding.patch_replication_pane(source)
        self.assertEqual(patched.count("inWizard or feature.isSupported('FEATURE_PEER_REPLICATION')"), 2)
        self.assertIn("inWizard or feature.isSupported('FEATURE_OFFSITE')", patched)
        self.assertEqual(branding.patch_replication_pane(patched), patched)

    def test_synchronize_page_shows_recovera_replication_once(self):
        branding = load_module()
        modern = """{% block scripts %}
    <script type="text/javascript" src="{{ asset('commonlookandfeel/js/App/Synchronize/SynchronizeView.js') }}"></script>
    <script type="text/javascript" src="{{ asset('commonlookandfeel/js/App/Synchronize/ReplicationStatusView.js') }}"></script>
{% endblock %}
{% block content %}
    <div id="synchronizeBody">
        <div class="row">
"""
        vintage = """{% block scripts %}
    <script>var x = 1;</script>
{% endblock %}
{% block content %}
    <div class="row"></div>
{% endblock %}
"""
        for source in (modern, vintage):
            patched = branding.patch_synchronize_template(source)
            self.assertEqual(patched.count("RecoveraSynchronize.js"), 1)
            self.assertEqual(patched.count('id="recovera-sync-panel"'), 1)
            self.assertEqual(branding.patch_synchronize_template(patched), patched)
            self.assertIn("RecoveraSynchronize.js", patched.split("{% block content %}")[0])
        patched = branding.patch_synchronize_template(modern)
        self.assertLess(patched.index("ReplicationStatusView.js"), patched.index("RecoveraSynchronize.js"))
        self.assertLess(patched.index('id="synchronizeBody"'), patched.index('id="recovera-sync-panel"'))
        installer = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('template_paths("Synchronize/index.html.twig", vintage=True)', installer)
        self.assertIn('(resources / "RecoveraSynchronize.js", scripts / "Synchronize/RecoveraSynchronize.js")', installer)
        panel = (ROOT / "setup" / "branding" / "RecoveraSynchronize.js").read_text(encoding="utf-8")
        self.assertIn("/api/recovera/offsite-target/replication-activity", panel)
        self.assertNotIn("innerHTML", panel)
        # An unknown total still shows an animated, clearly active bar.
        self.assertIn("recovera-sync-indeterminate", panel)
        self.assertIn("@keyframes recovera-sync-slide", panel)
        self.assertIn("prefers-reduced-motion", panel)
        self.assertNotIn("opacity:.35", panel)

    def test_network_page_uses_recovera_connectivity_check(self):
        branding = load_module()
        for prefix in ("commonlookandfeel", "vintage"):
            source = (
                "<script src=\"{{ asset('" + prefix + "/js/App/Configure/Network/ConnectivityView.js') }}\"></script>\n"
                "<script type=\"text/javascript\">\n$(function () { view.render(); });\n</script>\n"
            )
            patched = branding.patch_network_status_template(source)
            self.assertEqual(patched.count("RecoveraNetworkCheck.js"), 1)
            self.assertEqual(branding.patch_network_status_template(patched), patched)
            self.assertLess(patched.index("ConnectivityView.js"), patched.index("RecoveraNetworkCheck.js"))
            self.assertLess(patched.index("RecoveraNetworkCheck.js"), patched.index("view.render()"))
        installer = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('template_paths("Configure/Network/ip.status.html.twig", vintage=True)', installer)
        self.assertIn('(resources / "RecoveraNetworkCheck.js", scripts / "Configure/Network/RecoveraNetworkCheck.js")', installer)
        override = (ROOT / "setup" / "branding" / "RecoveraNetworkCheck.js").read_text(encoding="utf-8")
        self.assertIn("View.prototype.renderView = function", override)
        self.assertIn("/api/recovera/offsite-target/", override)
        self.assertIn("'network-check'", override)
        self.assertIn("'network-check-last'", override)
        self.assertNotIn("v1/device/settings/network/check", override)
        self.assertIn("help.datto.com", override)
        self.assertNotIn("innerHTML", override)

    def test_home_page_replaces_native_universal_with_recovera_target(self):
        branding = load_module()
        source = """{% set numOffsiteTargets = deviceInfo.offsiteTargets|length %}
                <td class=\"label-dark w-33\">
                    {% if numOffsiteTargets == 0 %}
"""
        patched = branding.patch_home_device_info(source)
        self.assertIn("RecoveraHome.js", patched)
        self.assertIn('id="recovera-offsite-servers"', patched)
        self.assertEqual(branding.patch_home_device_info(patched), patched)

    def test_appliance_access_route_and_menu_are_idempotent(self):
        branding = load_module()
        routes = branding.add_routes("existing: true\n")
        self.assertIn("path: /configure/appliance-access", routes)
        self.assertEqual(branding.add_routes(routes), routes)

        visibility = "{% set showConfigureOffsiteSync = feature.isSupported('FEATURE_OFFSITE') and is_granted('PERMISSION_OFFSITE_WRITE') %}"
        visibility = branding.add_target_visibility(visibility)
        self.assertIn("showRecoveraAccess", visibility)
        self.assertEqual(branding.add_target_visibility(visibility), visibility)

        desktop = """{% if showConfigureNetworking or showConfigureOffsiteSync or showConfigureDeviceSettings %}
<ul class="dropdown-menu">
{% if showConfigureOffsiteSync %}
<li><a class="dropdown-item" href="{{ path('configure_offsite') }}">{{ "menu.configure.offsite"|trans }}</a></li>
{% endif %}
</ul>
{% endif %}
"""
        desktop = branding.add_target_menu(desktop)
        self.assertIn("path('recovera_target')", desktop)
        self.assertIn("path('recovera_access')", desktop)
        self.assertIn("showRecoveraTarget", desktop.splitlines()[0])
        self.assertIn("showRecoveraAccess", desktop.splitlines()[0])
        self.assertEqual(branding.add_target_menu(desktop), desktop)

        mobile = """{% if showConfigureDeviceSettings or showConfigureNetworking %}
<ul class="dropdown-menu">
<li><a class="dropdown-item ps-5 py-1 pe-0" href="{{ path('configure_device') }}">{{ "menu.configure.device"|trans }}</a></li>
</ul>
{% endif %}
"""
        mobile = branding.add_target_menu(mobile)
        self.assertIn('class="dropdown-item ps-5 py-1 pe-0"', mobile)
        self.assertIn("Off-site Target", mobile)
        self.assertIn("Appliance Access", mobile)
        self.assertEqual(branding.add_target_menu(mobile), mobile)

    def test_target_visibility_survives_stock_template_changes(self):
        branding = load_module()
        visibility = "{% set showConfigureDeviceSettings = true %}\n"
        patched = branding.add_target_visibility(visibility)
        self.assertTrue(patched.startswith("{% set showRecoveraTarget"))
        self.assertIn("showRecoveraAccess", patched)
        self.assertEqual(branding.add_target_visibility(patched), patched)

    def test_appliance_access_copy_supports_self_signed_local_pages(self):
        access = (ROOT / "setup" / "branding" / "RecoveraAccess.js").read_text()
        self.assertIn("navigator.clipboard.writeText", access)
        self.assertIn("document.execCommand('copy')", access)
        self.assertIn("document.createElement('textarea')", access)
        self.assertIn("selectDisplayedPassword", access)


class RecoveraBrandingLayoutTests(unittest.TestCase):
    """apply-branding.py and apply-peer-ui.py on 5.6.x and 5.12.x web trees."""

    TEMPLATES = {
        "Default/layout.base.html.twig": "<html><head></head><body></body></html>\n",
        "Synchronize/index.html.twig": (
            "{% block scripts %}\n"
            "    <script type=\"text/javascript\" src=\"{{ asset('PREFIXjs/App/Synchronize/ReplicationStatusView.js') }}\"></script>\n"
            "{% endblock %}\n{% block content %}\n    <div id=\"synchronizeBody\"></div>\n{% endblock %}\n"),
        "Configure/Network/ip.status.html.twig": (
            "<script src=\"{{ asset('PREFIXjs/App/Configure/Network/ConnectivityView.js') }}\"></script>\n"
            "<script>view.render()</script>\n"),
        "Agents/List/index.html.twig": "{% block scripts %}\n{% endblock %}\n",
        "Assets/Configure/cloud.backup.html.twig": "<div></div>\n",
    }

    def build_tree(self, root: Path, legacy: bool) -> tuple[Path, Path]:
        device, web = root / "device", root / "web"
        prefix = "commonlookandfeel/" if legacy else ""
        layouts = ["commonlookandfeel/", "vintage/"] if legacy else [""]
        for layout in layouts:
            for name, text in self.TEMPLATES.items():
                path = device / "templates" / layout / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text.replace("PREFIX", layout), encoding="utf-8")
        (device / "config").mkdir(parents=True)
        (device / "config/routes.yaml").write_text("home:\n    path: /\n", encoding="utf-8")
        (web / prefix / "js/App").mkdir(parents=True)
        if legacy:
            # Real 5.6.x trees have the stock base layout; detection relies on it.
            stock = device / "templates/commonlookandfeel/Default/layout.base.html.twig"
            stock.parent.mkdir(parents=True, exist_ok=True)
            stock.write_text("<html><head></head><body></body></html>\n", encoding="utf-8")
        return device, web

    def run_branding(self, legacy: bool):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        device, web = self.build_tree(root, legacy)
        logo = root / "logo.png"
        logo.write_bytes(b"png")
        branding = load_module()
        with mock.patch.object(branding, "ROOT", device), mock.patch.object(branding, "WEB", web), \
             mock.patch.object(sys, "argv", ["apply-branding.py", str(logo)]), \
             mock.patch("builtins.print"):
            self.assertEqual(branding.main(), 0)
        spec = importlib.util.spec_from_file_location("recovera_peer_ui_test", PEER_UI)
        peer_ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(peer_ui)
        with mock.patch.object(peer_ui, "ROOT", device), mock.patch.object(peer_ui, "WEB_ROOT", web):
            self.assertEqual(peer_ui.main(), 0)
        return device, web

    def test_legacy_commonlookandfeel_layout(self):
        device, web = self.run_branding(legacy=True)
        templates = device / "templates"
        self.assertTrue((web / "commonlookandfeel/js/App/Configure/RecoveraTarget.js").is_file())
        self.assertTrue((web / "commonlookandfeel/UI/css/recovera-brand.css").is_file())
        self.assertTrue((web / "commonlookandfeel/js/App/Agents/RecoveraProtectStatus.js").is_file())
        target = (templates / "commonlookandfeel/Configure/RecoveraTarget/index.html.twig").read_text()
        self.assertIn("{% extends 'commonlookandfeel/Default/layout.main.html.twig' %}", target)
        self.assertIn("asset('commonlookandfeel/js/App/Configure/RecoveraTarget.js')", target)
        controller = (device / "src/App/Controller/Web/Configure/RecoveraTargetController.php").read_text()
        self.assertIn("render('commonlookandfeel/Configure/RecoveraTarget/index.html.twig')", controller)
        for layout in ("commonlookandfeel", "vintage"):
            sync = (templates / layout / "Synchronize/index.html.twig").read_text()
            self.assertIn("asset('commonlookandfeel/js/App/Synchronize/RecoveraSynchronize.js')", sync)
            network = (templates / layout / "Configure/Network/ip.status.html.twig").read_text()
            self.assertIn("asset('commonlookandfeel/js/App/Configure/Network/RecoveraNetworkCheck.js')", network)
            base = (templates / layout / "Default/layout.base.html.twig").read_text()
            self.assertIn('href="/commonlookandfeel/UI/css/recovera-brand.css?v=', base)
        status = (templates / "commonlookandfeel/Agents/List/index.html.twig").read_text()
        self.assertIn("asset('commonlookandfeel/js/App/Agents/RecoveraProtectStatus.js')", status)
        pane = (templates / "commonlookandfeel/Assets/Configure/cloud.backup.html.twig").read_text()
        self.assertIn("asset('commonlookandfeel/js/App/Agents/RecoveraProtectSystem.js')", pane)
        self.assertFalse((templates / "Configure").exists(), "nothing may be written to the flat path")

    def test_flat_512_layout(self):
        device, web = self.run_branding(legacy=False)
        templates = device / "templates"
        self.assertTrue((web / "js/App/Configure/RecoveraTarget.js").is_file())
        self.assertTrue((web / "UI/css/recovera-brand.css").is_file())
        self.assertFalse((web / "commonlookandfeel").exists())
        target = (templates / "Configure/RecoveraTarget/index.html.twig").read_text()
        self.assertIn("{% extends 'Default/layout.main.html.twig' %}", target)
        self.assertIn("asset('js/App/Configure/RecoveraTarget.js')", target)
        controller = (device / "src/App/Controller/Web/Configure/RecoveraTargetController.php").read_text()
        self.assertIn("render('Configure/RecoveraTarget/index.html.twig')", controller)
        sync = (templates / "Synchronize/index.html.twig").read_text()
        self.assertIn("asset('js/App/Synchronize/RecoveraSynchronize.js')", sync)
        self.assertIn('id="recovera-sync-panel"', sync)
        base = (templates / "Default/layout.base.html.twig").read_text()
        self.assertIn('href="/UI/css/recovera-brand.css?v=', base)
        self.assertIn('src="/js/App/Configure/RecoveraDeviceSettings.js"', base)
        status = (templates / "Agents/List/index.html.twig").read_text()
        self.assertIn("asset('js/App/Agents/RecoveraProtectStatus.js')", status)
        self.assertFalse((templates / "commonlookandfeel").exists())

    def test_stray_recovera_files_do_not_switch_a_flat_tree_to_legacy(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        device, web = self.build_tree(root, legacy=False)
        stray_template = device / "templates/commonlookandfeel/Configure/RecoveraTarget/index.html.twig"
        stray_template.parent.mkdir(parents=True)
        stray_template.write_text("old", encoding="utf-8")
        stray_js = web / "commonlookandfeel/js/App/Configure/RecoveraTarget.js"
        stray_js.parent.mkdir(parents=True)
        stray_js.write_text("old", encoding="utf-8")
        logo = root / "logo.png"
        logo.write_bytes(b"png")
        branding = load_module()
        with mock.patch.object(branding, "ROOT", device), mock.patch.object(branding, "WEB", web), \
             mock.patch.object(sys, "argv", ["apply-branding.py", str(logo)]), \
             mock.patch("builtins.print"):
            branding.main()
        self.assertEqual(branding.LAYOUT, "")
        self.assertFalse((device / "templates/commonlookandfeel").exists())
        self.assertFalse((web / "commonlookandfeel").exists())
        self.assertIn("asset('js/App/Synchronize/RecoveraSynchronize.js')",
                      (device / "templates/Synchronize/index.html.twig").read_text())
        # A legacy tree's own files are never removed.
        legacy_root = root / "legacy"
        legacy_device, legacy_web = self.build_tree(legacy_root, legacy=True)
        with mock.patch.object(branding, "ROOT", legacy_device), mock.patch.object(branding, "WEB", legacy_web):
            self.assertEqual(branding.detect_layout(), "commonlookandfeel/")


if __name__ == "__main__":
    unittest.main()
