#!/usr/bin/env python3
"""Collect a sanitized, content-free compatibility baseline from an appliance."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Iterable


SCHEMA = 1
COLLECTOR_VERSION = 1
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SENSITIVE_NAMES = {
    "authorized_keys", "credentials", "credential", "gshadow", "passwd",
    "password", "private", "secret", "secrets", "shadow", "token", "tokens",
}
SENSITIVE_SUFFIXES = {
    ".cer", ".crt", ".db", ".jks", ".key", ".kdb", ".p12", ".pem", ".pfx", ".pub", ".sqlite",
}


def is_sensitive_path(path: str | Path) -> bool:
    value = str(path).replace("\\", "/").lower()
    parts = [part for part in value.split("/") if part]
    name = parts[-1] if parts else ""
    stem = name.rsplit(".", 1)[0]
    if any(part in SENSITIVE_NAMES for part in parts):
        return True
    if any(token in SENSITIVE_NAMES for token in re.split(r"[^a-z0-9]+", value) if token):
        return True
    if stem.startswith(("id_rsa", "id_ed25519", "ssh_host_")):
        return True
    return any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_os_release(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1)
        if key in {"ID", "VERSION_ID", "VERSION_CODENAME"}:
            result[key.lower()] = value.strip().strip('"')
    return result


def parse_dpkg_status(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    packages: list[dict[str, str]] = []
    for paragraph in path.read_text(encoding="utf-8", errors="replace").split("\n\n"):
        fields: dict[str, str] = {}
        for line in paragraph.splitlines():
            if ": " in line and not line.startswith((" ", "\t")):
                key, value = line.split(": ", 1)
                fields[key] = value
        if fields.get("Status") != "install ok installed" or "Package" not in fields:
            continue
        packages.append({
            "name": fields["Package"],
            "version": fields.get("Version", ""),
            "architecture": fields.get("Architecture", ""),
        })
    return sorted(packages, key=lambda item: (item["name"], item["architecture"]))


def collect_packages(root: Path) -> list[dict[str, str]]:
    if root == Path("/") and shutil.which("dpkg-query"):
        command = [
            "dpkg-query", "-W",
            "-f=${binary:Package}\\t${Version}\\t${Architecture}\\t${db:Status-Abbrev}\\n",
        ]
        process = subprocess.run(command, text=True, capture_output=True, check=True)
        packages = []
        for line in process.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) == 4 and fields[3].startswith("ii"):
                packages.append({"name": fields[0], "version": fields[1], "architecture": fields[2]})
        return sorted(packages, key=lambda item: (item["name"], item["architecture"]))
    return parse_dpkg_status(root / "var/lib/dpkg/status")


def collect_services(root: Path) -> list[dict[str, str]]:
    if root != Path("/") or not shutil.which("systemctl"):
        return []
    command = [
        "systemctl", "list-unit-files", "--no-legend", "--no-pager",
        "--type=service,timer,socket,path",
    ]
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    if process.returncode:
        detail = process.stderr.strip() or f"exit status {process.returncode}"
        raise RuntimeError(f"systemd unit inventory failed: {detail}")
    services: list[dict[str, str]] = []
    for line in process.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2:
            item = {"name": fields[0], "unit_file_state": fields[1]}
            if len(fields) >= 3:
                item["preset"] = fields[2]
            services.append(item)
    return sorted(services, key=lambda item: item["name"])


def iter_rule_paths(root: Path, rule: dict[str, Any]) -> Iterable[tuple[Path, str]]:
    logical_root = "/" + str(rule["path"]).replace("\\", "/").lstrip("/")
    actual_root = root / logical_root.lstrip("/")
    if not actual_root.exists():
        return
    iterator = actual_root.rglob("*") if rule.get("recursive", False) else actual_root.glob("*")
    extensions = {str(value).lower() for value in rule.get("extensions", [])}
    for path in iterator:
        logical = "/" + path.relative_to(root).as_posix()
        if is_sensitive_path(logical):
            continue
        if path.is_file() and extensions and path.suffix.lower() not in extensions:
            continue
        if path.is_file() or path.is_symlink():
            yield path, logical


def collect_files(root: Path, policy: dict[str, Any]) -> list[dict[str, Any]]:
    maximum = int(policy.get("max_file_size", 16 * 1024 * 1024))
    entries: dict[str, dict[str, Any]] = {}
    for rule in policy.get("rules", []):
        for path, logical in iter_rule_paths(root, rule):
            info = path.lstat()
            entry: dict[str, Any] = {
                "path": logical,
                "mode": f"{stat.S_IMODE(info.st_mode):04o}",
            }
            if path.is_symlink():
                entry["type"] = "symlink"
                entry["target"] = os.readlink(path)
            else:
                entry["type"] = "file"
                entry["size"] = info.st_size
                if rule.get("hash", True) and info.st_size <= maximum:
                    entry["sha256"] = sha256_file(path)
            entries[logical] = entry
    return [entries[key] for key in sorted(entries)]


def compatibility_fingerprint(payload: dict[str, Any]) -> str:
    stable = {key: value for key, value in payload.items() if key not in {"generated_at", "fingerprint"}}
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_baseline(root: Path, label: str, policy: dict[str, Any]) -> dict[str, Any]:
    os_release = parse_os_release(root / "etc/os-release")
    live = root == Path("/")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "collector_version": COLLECTOR_VERSION,
        "label": label,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "privacy": "metadata-and-digests-only",
        "platform": {
            "architecture": platform.machine() if live else "offline-root",
            "kernel": platform.release() if live else None,
            "os": os_release,
        },
        "packages": collect_packages(root),
        "services": collect_services(root),
        "files": collect_files(root, policy),
    }
    payload["fingerprint"] = compatibility_fingerprint(payload)
    return payload


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="non-sensitive baseline name")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--root", default=Path("/"), type=Path, help="alternate offline filesystem root")
    args = parser.parse_args()
    if not LABEL_RE.fullmatch(args.label):
        parser.error("label must use only letters, numbers, dots, underscores, or hyphens")
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    if policy.get("schema") != 1:
        parser.error("unsupported collection policy schema")
    baseline = build_baseline(args.root.resolve(), args.label, policy)
    atomic_write_json(args.output.resolve(), baseline)
    print(f"wrote {args.output}: {baseline['fingerprint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
