import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "setup" / "branding" / "apply-peer-ui.py"


def load_module():
    spec = importlib.util.spec_from_file_location("recovera_peer_ui_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecoveraPeerUiTests(unittest.TestCase):
    def test_status_script_is_inside_twig_scripts_block_and_is_idempotent(self):
        peer_ui = load_module()
        script = "<script src=\"RecoveraProtectStatus.js\"></script>"
        original = """{% extends 'layout.html.twig' %}
{% block scripts %}
    <script src="native.js"></script>
{% endblock %}
{% block content %}Protect{% endblock %}
<script src="RecoveraProtectStatus.js"></script>
"""
        with tempfile.TemporaryDirectory() as tempdir:
            template = Path(tempdir) / "index.html.twig"
            template.write_text(original, encoding="utf-8")
            peer_ui.add_script_to_block(template, "RecoveraProtectStatus.js", script)
            first = template.read_text(encoding="utf-8")
            peer_ui.add_script_to_block(template, "RecoveraProtectStatus.js", script)
            second = template.read_text(encoding="utf-8")

        self.assertEqual(first, second)
        self.assertEqual(first.count("RecoveraProtectStatus.js"), 1)
        self.assertLess(first.index("RecoveraProtectStatus.js"), first.index("{% endblock %}"))


if __name__ == "__main__":
    unittest.main()
