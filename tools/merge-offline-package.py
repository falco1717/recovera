#!/usr/bin/env python3
"""Merge a CI-built Debian package repository into an offline installer payload."""

from __future__ import annotations

import argparse
import gzip
import hashlib
from pathlib import Path
import shutil
from typing import Iterable


def paragraphs(text: str) -> list[str]:
    return [value.strip() for value in text.replace("\r\n", "\n").split("\n\n") if value.strip()]


def fields(paragraph: str) -> dict[str, str]:
    result: dict[str, str] = {}
    key = None
    for line in paragraph.splitlines():
        if line.startswith((" ", "\t")) and key:
            result[key] += "\n" + line
        elif ": " in line:
            key, value = line.split(": ", 1)
            result[key] = value
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_gzip(path: Path, content: bytes) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as zipped:
            zipped.write(content)


def checksum_lines(paths: Iterable[Path]) -> str:
    return "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(paths, key=lambda item: item.name))


def merge(repository: Path, package_repository: Path, package_list: Path) -> list[str]:
    target_index = repository / "Packages"
    source_index = package_repository / "Packages"
    if not target_index.is_file() or not source_index.is_file():
        raise ValueError("both source and target repositories must contain Packages")

    current = paragraphs(target_index.read_text(encoding="utf-8"))
    incoming = paragraphs(source_index.read_text(encoding="utf-8"))
    if not incoming:
        raise ValueError("source repository contains no packages")

    replacements: dict[tuple[str, str], tuple[str, dict[str, str]]] = {}
    copied: list[str] = []
    for paragraph in incoming:
        metadata = fields(paragraph)
        required = {"Package", "Version", "Architecture", "Filename", "SHA256"}
        missing = required - metadata.keys()
        if missing:
            raise ValueError(f"source package metadata missing: {', '.join(sorted(missing))}")
        source_deb = package_repository / Path(metadata["Filename"]).name
        if not source_deb.is_file() or sha256(source_deb) != metadata["SHA256"]:
            raise ValueError(f"source package checksum mismatch: {source_deb.name}")
        destination = repository / source_deb.name
        shutil.copy2(source_deb, destination)
        metadata["Filename"] = f"./{destination.name}"
        normalized = []
        for line in paragraph.splitlines():
            normalized.append(f"Filename: ./{destination.name}" if line.startswith("Filename: ") else line)
        replacements[(metadata["Package"], metadata["Architecture"])] = ("\n".join(normalized), metadata)
        copied.append(destination.name)

    retained: list[str] = []
    for paragraph in current:
        metadata = fields(paragraph)
        key = (metadata.get("Package", ""), metadata.get("Architecture", ""))
        if key in replacements:
            old_name = Path(metadata.get("Filename", "")).name
            old_path = repository / old_name
            if old_name and old_path.exists() and old_name not in copied:
                old_path.unlink()
        else:
            retained.append(paragraph)

    merged = retained + [value[0] for _, value in sorted(replacements.items())]
    encoded = ("\n\n".join(merged) + "\n\n").encode()
    target_index.write_bytes(encoded)
    write_gzip(repository / "Packages.gz", encoded)

    versions: dict[str, str] = {}
    if package_list.is_file():
        for line in package_list.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                name, version = line.split("=", 1)
                versions[name] = version
    for _, metadata in replacements.values():
        versions[metadata["Package"]] = metadata["Version"]
    package_list.write_text("".join(f"{name}={versions[name]}\n" for name in sorted(versions)), encoding="utf-8")

    indexed = list(repository.glob("*.deb")) + [repository / "Packages", repository / "Packages.gz"]
    (repository / "SHA256SUMS").write_text(checksum_lines(indexed), encoding="utf-8")
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--package-repository", required=True, type=Path)
    parser.add_argument("--package-list", required=True, type=Path)
    args = parser.parse_args()
    copied = merge(args.repository.resolve(), args.package_repository.resolve(), args.package_list.resolve())
    print("merged: " + " ".join(copied))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
