#!/usr/bin/env python3
"""Compare two sanitized appliance compatibility baselines."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable


SCHEMA = 1


def load_baseline(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA:
        raise ValueError(f"{path}: unsupported baseline schema")
    if value.get("privacy") != "metadata-and-digests-only":
        raise ValueError(f"{path}: baseline is not marked as sanitized")
    return value


def keyed(items: list[dict[str, Any]], key: Callable[[dict[str, Any]], str]) -> dict[str, dict[str, Any]]:
    return {key(item): item for item in items}


def diff_items(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    key: Callable[[dict[str, Any]], str],
) -> dict[str, list[Any]]:
    left, right = keyed(before, key), keyed(after, key)
    added = [right[name] for name in sorted(right.keys() - left.keys())]
    removed = [left[name] for name in sorted(left.keys() - right.keys())]
    changed = [
        {"key": name, "before": left[name], "after": right[name]}
        for name in sorted(left.keys() & right.keys())
        if left[name] != right[name]
    ]
    return {"added": added, "removed": removed, "changed": changed}


def build_comparison(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    packages = diff_items(
        before.get("packages", []), after.get("packages", []),
        lambda item: f"{item['name']}:{item.get('architecture', '')}",
    )
    services = diff_items(before.get("services", []), after.get("services", []), lambda item: item["name"])
    files = diff_items(before.get("files", []), after.get("files", []), lambda item: item["path"])
    platform_change = None
    if before.get("platform") != after.get("platform"):
        platform_change = {"before": before.get("platform"), "after": after.get("platform")}
    counts = {
        "packages_added": len(packages["added"]),
        "packages_removed": len(packages["removed"]),
        "packages_changed": len(packages["changed"]),
        "services_added": len(services["added"]),
        "services_removed": len(services["removed"]),
        "services_changed": len(services["changed"]),
        "files_added": len(files["added"]),
        "files_removed": len(files["removed"]),
        "files_changed": len(files["changed"]),
    }
    high_attention = counts["packages_removed"] + counts["services_removed"] + counts["files_removed"]
    changed_total = sum(counts.values()) + int(platform_change is not None)
    return {
        "schema": SCHEMA,
        "before": {"label": before["label"], "fingerprint": before["fingerprint"]},
        "after": {"label": after["label"], "fingerprint": after["fingerprint"]},
        "summary": {
            "classification": "high-attention" if high_attention else ("review" if changed_total else "no-change"),
            "high_attention_removals": high_attention,
            "total_changes": changed_total,
            **counts,
        },
        "platform": platform_change,
        "packages": packages,
        "services": services,
        "files": files,
    }


def markdown_report(comparison: dict[str, Any]) -> str:
    summary = comparison["summary"]
    lines = [
        "# Appliance compatibility comparison",
        "",
        f"- Before: `{comparison['before']['label']}` (`{comparison['before']['fingerprint']}`)",
        f"- After: `{comparison['after']['label']}` (`{comparison['after']['fingerprint']}`)",
        f"- Classification: **{summary['classification']}**",
        f"- Total changes: **{summary['total_changes']}**",
        "",
        "| Surface | Added | Removed | Changed |",
        "| --- | ---: | ---: | ---: |",
        f"| Packages | {summary['packages_added']} | {summary['packages_removed']} | {summary['packages_changed']} |",
        f"| Services | {summary['services_added']} | {summary['services_removed']} | {summary['services_changed']} |",
        f"| Files | {summary['files_added']} | {summary['files_removed']} | {summary['files_changed']} |",
        "",
        "## Review order",
        "",
        "1. Removed packages, units, and files that Recovera contracts depend upon.",
        "2. Platform, kernel, storage, virtualization, and boot changes.",
        "3. Changed web, API, service, and package surfaces listed in the Recovera overlay manifest.",
        "4. Added components and configuration defaults.",
        "5. Full Recovera acceptance suite before any production rollout.",
        "",
    ]
    for surface in ("packages", "services", "files"):
        section = comparison[surface]
        lines.extend([f"## {surface.title()}", ""])
        for kind in ("removed", "changed", "added"):
            lines.append(f"### {kind.title()} ({len(section[kind])})")
            lines.append("")
            values = section[kind]
            if not values:
                lines.append("None.")
            else:
                for item in values:
                    name = item.get("key") or item.get("name") or item.get("path")
                    lines.append(f"- `{name}`")
            lines.append("")
    return "\n".join(lines)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--json", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    args = parser.parse_args()
    comparison = build_comparison(load_baseline(args.before), load_baseline(args.after))
    atomic_write(args.json, json.dumps(comparison, indent=2, sort_keys=True) + "\n")
    atomic_write(args.markdown, markdown_report(comparison))
    print(f"{comparison['summary']['classification']}: {comparison['summary']['total_changes']} changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
