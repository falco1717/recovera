"""Signed, stateless appliance access tokens for Recovera update gateways."""

import base64
import json
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time


IDENTITY = "recovera-gateway-access"
NAMESPACE = "recovera-gateway-access"
SUBJECT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}")
CHANNEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
JTI_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")


class AccessError(RuntimeError):
    pass


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise AccessError("invalid token encoding")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError as exc:
        raise AccessError("invalid token encoding") from exc


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def issue(signing_key, subject, channels, lifetime, now=None):
    now = int(time.time() if now is None else now)
    if not SUBJECT_RE.fullmatch(subject):
        raise AccessError("invalid token subject")
    channels = sorted(set(channels))
    if not channels or any(not CHANNEL_RE.fullmatch(item) for item in channels):
        raise AccessError("invalid token channel")
    if not 300 <= lifetime <= 366 * 24 * 3600:
        raise AccessError("token lifetime must be between 5 minutes and 366 days")
    payload = canonical({
        "channels": channels,
        "exp": now + lifetime,
        "iat": now,
        "jti": secrets.token_urlsafe(24),
        "sub": subject,
        "v": 1,
    })
    with tempfile.TemporaryDirectory(prefix="recovera-gateway-token-") as directory:
        source = Path(directory) / "payload.json"
        source.write_bytes(payload)
        result = subprocess.run([
            "ssh-keygen", "-Y", "sign", "-q", "-f", str(signing_key),
            "-n", NAMESPACE, str(source),
        ], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise AccessError(result.stderr.decode("utf-8", "replace").strip() or "token signing failed")
        signature = source.with_name(source.name + ".sig").read_bytes()
    return f"rgt1.{encode(payload)}.{encode(signature)}"


def verify(token, signers, channel, revoked=None, now=None, clock_skew=60):
    try:
        prefix, encoded_payload, encoded_signature = token.split(".", 2)
    except ValueError as exc:
        raise AccessError("invalid gateway token") from exc
    if prefix != "rgt1":
        raise AccessError("unsupported gateway token")
    payload = decode(encoded_payload)
    signature = decode(encoded_signature)
    with tempfile.TemporaryDirectory(prefix="recovera-gateway-verify-") as directory:
        signature_path = Path(directory) / "token.sig"
        signature_path.write_bytes(signature)
        result = subprocess.run([
            "ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", IDENTITY,
            "-n", NAMESPACE, "-s", str(signature_path),
        ], input=payload, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode:
            raise AccessError("invalid gateway token signature")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AccessError("invalid gateway token payload") from exc
    if canonical(value) != payload or set(value) != {"channels", "exp", "iat", "jti", "sub", "v"}:
        raise AccessError("non-canonical gateway token payload")
    now = int(time.time() if now is None else now)
    if value["v"] != 1 or not SUBJECT_RE.fullmatch(str(value["sub"])):
        raise AccessError("invalid gateway token identity")
    if not JTI_RE.fullmatch(str(value["jti"])):
        raise AccessError("invalid gateway token identifier")
    if not isinstance(value["channels"], list) or channel not in value["channels"]:
        raise AccessError("gateway token is not authorized for this channel")
    if any(not isinstance(item, str) or not CHANNEL_RE.fullmatch(item) for item in value["channels"]):
        raise AccessError("invalid gateway token channels")
    if not isinstance(value["iat"], int) or not isinstance(value["exp"], int):
        raise AccessError("invalid gateway token lifetime")
    if value["iat"] > now + clock_skew or value["exp"] <= now - clock_skew:
        raise AccessError("gateway token is expired or not yet valid")
    if value["exp"] - value["iat"] > 366 * 24 * 3600:
        raise AccessError("gateway token lifetime exceeds policy")
    if value["jti"] in (revoked or set()):
        raise AccessError("gateway token has been revoked")
    return value
