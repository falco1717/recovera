import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "setup" / "branding" / "apply-branding.py"
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
        self.assertIn("Recovera Updates", cleanup)
        self.assertIn("update-install", cleanup)
        self.assertIn("input[name=\"csrf\"]", cleanup)

    def test_console_and_login_branding_are_recovera_owned(self):
        logo = (ROOT / "setup" / "branding" / "recovera-ascii.logo").read_text()
        motd = (ROOT / "setup" / "branding" / "recovera-motd").read_text()
        installer = (ROOT / "setup" / "setup.sh").read_text()

        self.assertNotIn("Datto", logo)
        self.assertIn("R E C O V E R A", motd)
        self.assertIn("/usr/lib/datto/statusshell/logo/0.logo", installer)
        self.assertIn("chmod a-x /etc/update-motd.d/25-datto", installer)
        self.assertIn("/etc/update-motd.d/25-recovera", installer)

    def test_recovery_points_bridge_is_injected_once_after_native_view(self):
        branding = load_module()
        source = """{% block scripts %}
<script src=\"{{ asset('commonlookandfeel/js/App/Assets/RecoveryPointsView.js') }}\"></script>
{% endblock %}
{% block content %}<main></main>{% endblock %}
"""
        patched = branding.patch_recovery_points_template(source)
        self.assertIn("RecoveraRecoveryPoints.js", patched)
        self.assertIn("recovera-recovery-points-csrf", patched)
        self.assertLess(patched.index("RecoveryPointsView.js"),
                        patched.index("RecoveraRecoveryPoints.js"))
        self.assertEqual(branding.patch_recovery_points_template(patched), patched)

    def test_protect_system_enables_recovera_replication_bridge_once(self):
        branding = load_module()
        source = """{% set cloudPaneTitle = feature.isSupported('FEATURE_PEER_REPLICATION') %}
{% block wizard_assets %}
    <script type=\"text/javascript\" src=\"{{ asset('commonlookandfeel/js/App/Agents/WizardSystem.js') }}\"></script>
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


if __name__ == "__main__":
    unittest.main()
