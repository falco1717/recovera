#!/usr/bin/env python3
"""Verify a signed Recovera release directory without trusting its host."""

import argparse
import hashlib
import json
import lzma
from pathlib import Path
import re
import shutil
import subprocess
import sys


SAFE_ASSET = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_~-]{0,191}")
SHA256 = re.compile(r"[0-9a-f]{64}")


class VerificationError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_asset(name):
    return isinstance(name, str) and Path(name).name == name and SAFE_ASSET.fullmatch(name)


def asset_path(directory, name):
    if not safe_asset(name):
        raise VerificationError(f"unsafe release asset name: {name!r}")
    directory = Path(directory).resolve()
    path = directory / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != directory:
        raise VerificationError(f"release asset is missing or unsafe: {name}")
    return path


def verify_asset(directory, metadata):
    if set(metadata) < {"name", "size", "sha256"}:
        raise VerificationError("asset metadata is incomplete")
    name = metadata["name"]
    path = asset_path(directory, name)
    try:
        expected_size = int(metadata["size"])
    except (TypeError, ValueError) as exc:
        raise VerificationError(f"invalid size for {name}") from exc
    expected_digest = str(metadata["sha256"])
    if expected_size < 1 or not SHA256.fullmatch(expected_digest):
        raise VerificationError(f"invalid size or digest for {name}")
    if path.stat().st_size != expected_size:
        raise VerificationError(f"size mismatch for {name}")
    actual = sha256_file(path)
    if actual != expected_digest:
        raise VerificationError(f"SHA-256 mismatch for {name}")
    return {"name": name, "size": expected_size, "sha256": actual}


def verify_package_assets(directory, manifest):
    if manifest.get("schema") != 2 or manifest.get("type") != "package":
        raise VerificationError("not a schema-2 package manifest")
    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise VerificationError("package manifest contains no packages")
    seen = set()
    verified = []
    for package in packages:
        if not isinstance(package, dict) or not {"asset", "size", "sha256"} <= set(package):
            raise VerificationError("package metadata is incomplete")
        name = package["asset"]
        if name in seen:
            raise VerificationError(f"duplicate package asset: {name}")
        seen.add(name)
        verified.append(verify_asset(directory, {
            "name": name, "size": package["size"], "sha256": package["sha256"],
        }))
    if int(manifest.get("download_size", -1)) != sum(item["size"] for item in verified):
        raise VerificationError("package download_size does not match its assets")
    return verified


def verify_image_assets(directory, manifest, verify_uncompressed=False):
    image = manifest.get("image")
    if manifest.get("schema") != 1 or not isinstance(image, dict) or image.get("compression") != "xz":
        raise VerificationError("not a supported schema-1 image manifest")
    parts = image.get("parts")
    if not isinstance(parts, list) or not parts:
        raise VerificationError("image manifest contains no parts")
    verified = [verify_asset(directory, part) for part in parts]
    compressed_digest = hashlib.sha256()
    compressed_size = 0
    uncompressed_digest = hashlib.sha256()
    uncompressed_size = 0
    decompressor = lzma.LZMADecompressor() if verify_uncompressed else None
    for part in parts:
        with asset_path(directory, part["name"]).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                compressed_digest.update(block)
                compressed_size += len(block)
                if decompressor is not None:
                    output = decompressor.decompress(block)
                    uncompressed_digest.update(output)
                    uncompressed_size += len(output)
    if compressed_size != int(image.get("size", -1)) or compressed_digest.hexdigest() != image.get("sha256"):
        raise VerificationError("combined image size or SHA-256 mismatch")
    if decompressor is not None:
        if not decompressor.eof:
            raise VerificationError("compressed image is incomplete")
        if (uncompressed_size != int(image.get("uncompressed_size", -1)) or
                uncompressed_digest.hexdigest() != image.get("uncompressed_sha256")):
            raise VerificationError("uncompressed image size or SHA-256 mismatch")
    return verified


def verify_signature(manifest_path, signature_path, signers, identity, namespace):
    if not shutil.which("ssh-keygen"):
        raise VerificationError("ssh-keygen is required")
    command = [
        "ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", identity,
        "-n", namespace, "-s", str(signature_path),
    ]
    result = subprocess.run(
        command, input=Path(manifest_path).read_bytes(), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    if result.returncode:
        detail = result.stdout.decode("utf-8", "replace").strip()
        raise VerificationError(f"manifest signature verification failed: {detail}")


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--directory", required=True, type=Path)
    value.add_argument("--manifest", default="recovera-package-manifest.json")
    value.add_argument("--signature")
    value.add_argument("--signers", required=True, type=Path)
    value.add_argument("--identity", default="recovera-release")
    value.add_argument("--namespace", default="recovera-upgrade")
    value.add_argument("--verify-uncompressed", action="store_true")
    return value


def main(argv=None):
    arguments = parser().parse_args(argv)
    directory = arguments.directory.resolve()
    manifest_path = asset_path(directory, arguments.manifest)
    signature_name = arguments.signature or arguments.manifest + ".sig"
    signature_path = asset_path(directory, signature_name)
    if not arguments.signers.is_file():
        raise VerificationError(f"signer list is missing: {arguments.signers}")
    verify_signature(
        manifest_path, signature_path, arguments.signers,
        arguments.identity, arguments.namespace,
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VerificationError("manifest is not valid JSON") from exc
    if manifest.get("type") == "package":
        assets = verify_package_assets(directory, manifest)
    else:
        assets = verify_image_assets(directory, manifest, arguments.verify_uncompressed)
    print(json.dumps({
        "assets": assets,
        "manifest": manifest_path.name,
        "manifest_sha256": sha256_file(manifest_path),
        "sequence": manifest.get("sequence"),
        "signature": signature_path.name,
        "signature_valid": True,
        "type": manifest.get("type", "image"),
        "version": manifest.get("version"),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except VerificationError as exc:
        print(f"verify-release: {exc}", file=sys.stderr)
        sys.exit(1)
