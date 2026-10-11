#!/usr/bin/env python3
"""Remove source-appliance identity and excluded dependencies from a deb tree."""

from __future__ import annotations

import pathlib
import re
import shutil
import sys
import hashlib


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


if len(sys.argv) != 3:
    die("usage: sanitize-datto-package.py EXTRACTED_DEB PRUNE_LIST")

root = pathlib.Path(sys.argv[1]).resolve()
prune_file = pathlib.Path(sys.argv[2]).resolve()
control = root / "DEBIAN" / "control"
if not control.is_file():
    die(f"missing Debian control file: {control}")

pruned = {
    line.strip()
    for line in prune_file.read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.lstrip().startswith("#")
}


def package_name(requirement: str) -> str:
    first_alternative = requirement.split("|", 1)[0]
    without_version = re.sub(r"\s*\([^)]*\)", "", first_alternative)
    without_arch = re.sub(r":(?:any|native)$", "", without_version.strip())
    return without_arch.strip()


text = control.read_text(encoding="utf-8")
match = re.search(r"(?ms)^Depends:\s*(.*?)(?=\n\S[^:]*:|\Z)", text)
if not match:
    die("datto-siris-os-2 has no Depends field")

raw = re.sub(r"\n[ \t]+", " ", match.group(1)).strip()
requirements = [item.strip() for item in raw.split(",") if item.strip()]
removed = [item for item in requirements if package_name(item) in pruned]
kept = [item for item in requirements if package_name(item) not in pruned]
if not removed:
    die("no excluded dependencies were found in datto-siris-os-2")

wrapped = "Depends: " + ",\n ".join(kept)
text = text[: match.start()] + wrapped + text[match.end() :]
control.write_text(text, encoding="utf-8")

# Never clone the originating appliance's TLS/log-shipping private identity or
# configuration/service units for packages intentionally excluded above.
removed_paths = (
    "etc/apache2/ssl/www.key",
    "etc/apache2/ssl/www.crt",
    "etc/filebeat",
    "etc/fluent-bit",
    "etc/rsyslog.d/60-fluent-bit.conf",
    "etc/sudoers.d/telegraf",
    "etc/telegraf",
    "lib/systemd/system/al-agent.service.d",
    "lib/systemd/system/datto-configure-wiz-sensor-on-startup.service",
    "lib/systemd/system/datto-filebeat-configure.service",
    "lib/systemd/system/datto-telegraf-configure.service",
    "lib/systemd/system/falcon-sensor.service.d",
    "lib/systemd/system/filebeat.service.d",
    "lib/systemd/system/fluent-bit.service.d",
    "lib/systemd/system/telegraf.service.d",
    "lib/systemd/system/wiz-sensor.service.d",
)
for relative in removed_paths:
    path = root / relative
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()

# The application PHP-FPM pool assigned its socket to Telegraf solely so that
# the removed telemetry agent could scrape statistics. Apache already connects
# as www-data; make that the socket group and remove the stale explanation.
fpm_pool = root / "etc" / "php" / "8.1" / "fpm" / "pool.d" / "siris.conf"
if not fpm_pool.is_file():
    die("missing application PHP-FPM pool configuration")
fpm_text = fpm_pool.read_text(encoding="utf-8")
fpm_text, count = re.subn(
    r"; We need to set the ownership on the fpm unix-socket in such a way that\n"
    r"; telegraf \(running as telegraf:telegraf\) can read/write it in order to ?\n"
    r"; gather stats\.\n",
    "; Apache connects to the application socket as www-data.\n",
    fpm_text,
)
if count != 1:
    die(f"expected one Telegraf PHP-FPM comment block, found {count}")
fpm_text, count = re.subn(
    r"(?m)^([ \t]*listen\.group[ \t]*=[ \t]*)telegraf([ \t]*)$",
    r"\1www-data\2",
    fpm_text,
)
if count != 1:
    die(f"expected one Telegraf PHP-FPM socket group, found {count}")
fpm_pool.write_text(fpm_text, encoding="utf-8")

conffiles = root / "DEBIAN" / "conffiles"
if conffiles.is_file():
    removed_conffile_prefixes = tuple(f"/{relative}" for relative in removed_paths)
    retained = [
        line
        for line in conffiles.read_text(encoding="utf-8").splitlines()
        if not any(
            line.strip() == prefix or line.strip().startswith(prefix + "/")
            for prefix in removed_conffile_prefixes
        )
    ]
    conffiles.write_text("\n".join(retained) + "\n", encoding="utf-8")

# The vendor postinst hard-fails if Telegraf is absent and presets other
# excluded agent services. Remove only those agent-specific operations.
postinst = root / "DEBIAN" / "postinst"
if not postinst.is_file():
    die("datto-siris-os-2 has no postinst")
postinst_text = postinst.read_text(encoding="utf-8")
telegraf_block = re.compile(
    r"\n        # The Telegraf package does not install its systemd unit file\..*?"
    r"        # End of Telegraf systemd unit file installation code\.\n",
    re.DOTALL,
)
postinst_text, count = telegraf_block.subn("\n", postinst_text)
if count != 1:
    die(f"expected one Telegraf postinst block, found {count}")
postinst_text, count = re.subn(
    r"\n        # Add the telegraf service account.*?\n        usermod -a -G ssl-cert telegraf \|\| true\n",
    "\n",
    postinst_text,
    flags=re.DOTALL,
)
if count != 1:
    die(f"expected one Telegraf account postinst block, found {count}")
for service in (
    "fluent-bit.service",
    "telegraf.service",
    "al-agent.service",
    "filebeat.service",
):
    postinst_text, count = re.subn(
        rf"^            {re.escape(service)}(?: \\)?\n", "", postinst_text, flags=re.MULTILINE
    )
    if count != 1:
        die(f"expected one {service} postinst preset entry, found {count}")
postinst_text = postinst_text.replace(
    "            dtcserver.service \\\n", "            dtcserver.service\n", 1
)
postinst.write_text(postinst_text, encoding="utf-8")

preset = root / "lib" / "systemd" / "system-preset" / "10-datto-siris-os-2.preset"
if preset.is_file():
    agent_pattern = re.compile(r"(al-agent|falcon-sensor|filebeat|fluent-bit|telegraf|wiz-sensor)")
    preset_lines = [
        line
        for line in preset.read_text(encoding="utf-8").splitlines()
        if not agent_pattern.search(line)
    ]
    preset.write_text("\n".join(preset_lines) + "\n", encoding="utf-8")

# The repacked source package contained active root and aurorauser hashes in a
# factory-default shadow template. Preserve the accounts but lock every password.
shadow = root / "datto" / "def-configs" / "shadow"
if shadow.is_file():
    locked: list[str] = []
    for line in shadow.read_text(encoding="utf-8").splitlines():
        fields = line.split(":")
        if len(fields) >= 2:
            fields[1] = "!"
        locked.append(":".join(fields))
    shadow.write_text("\n".join(locked) + "\n", encoding="utf-8")

# dpkg-repack carries the source package's md5sums. Regenerate them after
# deleting identity files and locking the factory shadow template.
md5sums = root / "DEBIAN" / "md5sums"
entries: list[str] = []
for path in sorted(root.rglob("*")):
    if not path.is_file() or path.is_symlink() or root / "DEBIAN" in path.parents:
        continue
    digest = hashlib.md5(path.read_bytes()).hexdigest()  # Debian md5sums format
    entries.append(f"{digest}  {path.relative_to(root).as_posix()}")
md5sums.write_text("\n".join(entries) + "\n", encoding="utf-8")

print("removed dependencies:", " ".join(package_name(item) for item in removed))
print("removed source-appliance TLS identity and excluded-agent integration")
print("changed the PHP-FPM application socket group from telegraf to www-data")
print("locked password hashes in datto/def-configs/shadow")
