"""Public-mirror export helper (runs against a private apt root, no root needed).

  pkgplan2.py plan   <aptroot> <exportdir>  -> lists/pub-downloadable.txt, lists/pub-missing.tsv
  pkgplan2.py verify <exportdir>            -> lists/missing-debs.tsv (installed packages with no .deb)
"""
import os
import sys
import urllib.parse


def noepoch(v):
    return v.split(":", 1)[1] if ":" in v else v


mode = sys.argv[1]

if mode == "plan":
    import apt

    root, dest = sys.argv[2], sys.argv[3]
    lists = os.path.join(dest, "lists")
    cache = apt.Cache(rootdir=root)
    pub, missing = [], []
    for p in cache:
        if not p.is_installed:
            continue
        v = p.installed
        if v.downloadable:
            pub.append(f"{p.name}={v.version}")
        else:
            missing.append(f"{p.name}\t{v.version}\t{v.architecture}")
    with open(os.path.join(lists, "pub-downloadable.txt"), "w") as f:
        f.write("\n".join(sorted(pub)) + "\n")
    with open(os.path.join(lists, "pub-missing.tsv"), "w") as f:
        f.write("\n".join(sorted(missing)) + "\n")
    print(f"plan: {len(pub)} exact versions on the public Ubuntu mirror, {len(missing)} not")

elif mode == "verify":
    dest = sys.argv[2]
    lists = os.path.join(dest, "lists")
    got = set()
    for fn in os.listdir(os.path.join(dest, "debs")):
        if fn.endswith(".deb"):
            name, ver, _ = fn[:-4].split("_", 2)
            got.add((name, noepoch(urllib.parse.unquote(ver))))
    local = set(open(os.path.join(lists, "local-debs.txt")).read().split())
    missing = []
    for line in open(os.path.join(lists, "all-packages-versions.txt")):
        line = line.strip()
        if not line:
            continue
        name, ver = line.split("=", 1)
        if (name, noepoch(ver)) not in got:
            why = "local .deb only (vendor installer / Ubuntu Pro)" if name in local else "Datto repo only (blocked)"
            missing.append(f"{name}\t{ver}\t{why}")
    with open(os.path.join(lists, "missing-debs.tsv"), "w") as f:
        f.write("package\tversion\treason\n" + "\n".join(missing) + ("\n" if missing else ""))
    print(f"verify: {len(got)} .deb files, {len(missing)} installed packages without a .deb")
