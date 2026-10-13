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


if __name__ == "__main__":
    unittest.main()
