#!/usr/bin/env python3
"""Install Recovera peer controls into the native Protect interfaces."""
from pathlib import Path
import shutil

ROOT = Path("/usr/lib/datto/device")
WEB = Path("/datto/web/commonlookandfeel/js/App/Agents")
SOURCE = Path(__file__).parent
RECOVERA_PANEL = '''<div id="recovera-asset-replication" data-asset="{{ asset.keyName }}" class="card mt-3"><div class="d-none">{{ csrfTag() }}</div><div class="card-body"><h3>Recovera replication</h3><div id="recovera-asset-policy">Loading replication policy…</div></div></div>
<script type="text/javascript" src="{{ asset('commonlookandfeel/js/App/Agents/RecoveraProtectSystem.js') }}"></script>'''


def append_once(path: Path, marker: str, content: str) -> None:
    if not path.is_file():
        raise SystemExit(f"required Recovera template is missing: {path}")
    text = path.read_text(encoding="utf-8")
    if marker not in text:
        path.write_text(text.rstrip() + "\n" + content + "\n", encoding="utf-8")


def main() -> int:
    WEB.mkdir(parents=True, exist_ok=True)
    for name in ("RecoveraProtectSystem.js", "RecoveraProtectStatus.js"):
        shutil.copy2(SOURCE / name, WEB / name)
    append_once(
        ROOT / "templates/commonlookandfeel/Agents/List/index.html.twig",
        "RecoveraProtectStatus.js",
        '''<script type="text/javascript" src="{{ asset('commonlookandfeel/js/App/Agents/RecoveraProtectStatus.js') }}"></script>''',
    )
    pane = ROOT / "templates/commonlookandfeel/Assets/Configure/cloud.backup.html.twig"
    text = pane.read_text(encoding="utf-8")
    pane.write_text(text, encoding="utf-8")
    append_once(pane, "recovera-asset-replication", RECOVERA_PANEL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
