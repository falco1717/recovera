import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "setup" / "branding" / "apply-branding.py"


def load_module():
    spec = importlib.util.spec_from_file_location("recovera_branding_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecoveraBrandingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
