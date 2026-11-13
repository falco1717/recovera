#!/usr/bin/env python3
"""Install Recovera peer controls into the native Protect interfaces."""
from pathlib import Path
import shutil

ROOT = Path("/usr/lib/datto/device")
WEB_ROOT = Path("/datto/web")
SOURCE = Path(__file__).parent
# The per-asset Recovera replication editor belongs only on the Configure page.
# In the "Protect a System" wizard (inWizard) the native replication step already
# lets you pick a peer (RecoveraProtectSystem.js relabels it + populates the
# target list + hooks the save), so this standalone policy form must NOT render
# there — otherwise it shows a second, always-on form on top of the native
# No-Replication/Target toggle. Guard it with {% if not inWizard %}.
RECOVERA_PANEL = '''{% if not inWizard %}
<div id="recovera-asset-replication" data-asset="{{ asset.keyName }}" class="card mt-3"><div class="d-none">{{ csrfTag() }}</div><div class="card-body"><h3>Recovera replication</h3><div id="recovera-asset-policy">Loading replication policy…</div></div></div>
<script type="text/javascript" src="{{ asset('LAYOUTjs/App/Agents/RecoveraProtectSystem.js') }}"></script>
{% endif %}'''


def detect_layout(root: "Path | None" = None) -> str:
    """commonlookandfeel/ on images up to 5.6.x; the flat layout on 5.12.x."""
    root = ROOT if root is None else root
    # A stock 5.6.x template, not just the directory: Recovera files left in a
    # commonlookandfeel/ tree on a flat image must not switch the layout.
    return "commonlookandfeel/" if (root / "templates/commonlookandfeel/Default/layout.base.html.twig").is_file() else ""


def append_once(path: Path, marker: str, content: str) -> None:
    if not path.is_file():
        raise SystemExit(f"required Recovera template is missing: {path}")
    text = path.read_text(encoding="utf-8")
    if marker not in text:
        path.write_text(text.rstrip() + "\n" + content + "\n", encoding="utf-8")


def add_script_to_block(path: Path, marker: str, script: str) -> None:
    """Put a script inside Twig's scripts block, repairing older bad installs."""
    if not path.is_file():
        raise SystemExit(f"required Recovera template is missing: {path}")
    text = path.read_text(encoding="utf-8")
    text = "\n".join(line for line in text.splitlines() if marker not in line) + "\n"
    block_start = text.find("{% block scripts %}")
    block_end = text.find("{% endblock %}", block_start)
    if block_start < 0 or block_end < 0:
        raise SystemExit(f"Twig scripts block is missing: {path}")
    text = text[:block_end] + "    " + script + "\n" + text[block_end:]
    path.write_text(text, encoding="utf-8")


def main() -> int:
    layout = detect_layout()
    web = WEB_ROOT / layout / "js/App/Agents"
    templates = ROOT / "templates" / layout
    web.mkdir(parents=True, exist_ok=True)
    for name in ("RecoveraProtectSystem.js", "RecoveraProtectStatus.js"):
        shutil.copy2(SOURCE / name, web / name)
    add_script_to_block(
        templates / "Agents/List/index.html.twig",
        "RecoveraProtectStatus.js",
        f'''<script type="text/javascript" src="{{{{ asset('{layout}js/App/Agents/RecoveraProtectStatus.js') }}}}"></script>''',
    )
    pane = templates / "Assets/Configure/cloud.backup.html.twig"
    append_once(pane, "recovera-asset-replication", RECOVERA_PANEL.replace("LAYOUT", layout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
