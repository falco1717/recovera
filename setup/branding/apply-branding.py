#!/usr/bin/env python3
"""Apply Recovera branding without renaming compatibility-critical packages."""

from __future__ import annotations

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
    marker = "/commonlookandfeel/UI/css/recovera-brand.css"
    if marker in text:
        return text
    needle = "</head>"
    tag = f'    <link rel="stylesheet" href="{marker}" />\n'
    return text.replace(needle, tag + needle, 1)


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

    for path in (
        ROOT / "templates/commonlookandfeel/Default/layout.base.html.twig",
        ROOT / "templates/vintage/Default/layout.base.html.twig",
    ):
        update(path, add_global_branding)
    for relative in (
        "templates/commonlookandfeel/Default/desktop.menu.html.twig",
        "templates/commonlookandfeel/Default/mobile.menu.html.twig",
    ):
        update(ROOT / relative, replace_nav_logo)

    update(ROOT / "templates/commonlookandfeel/Authentication/index.login.html.twig", brand_login)
    update(ROOT / "templates/commonlookandfeel/Default/layout.wizard.three.html.twig", brand_wizard)

    for path in (ROOT / "translations").glob("*messages.en_US.yml"):
        update(path, brand_translation)
    update(WEB / "js/translations/en_US.js", brand_translation)

    for cache in (
        Path("/var/cache/datto/device/prod/twig"),
        Path("/var/cache/datto/device/prod/translations"),
    ):
        if cache.is_dir():
            shutil.rmtree(cache)

    print("Recovera branding applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
