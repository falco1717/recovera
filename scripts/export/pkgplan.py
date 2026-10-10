"""Package export helper.

  pkgplan.py plan   <exportdir>  -> lists/downloadable.txt, lists/not-downloadable.tsv, lists/by-repo.txt
  pkgplan.py verify <exportdir>  -> lists/download-failed.tsv (downloadable but no .deb landed)
"""
import collections
import os
import sys
import urllib.parse

mode, dest = sys.argv[1], sys.argv[2]
lists = os.path.join(dest, "lists")


def noepoch(v):
    return v.split(":", 1)[1] if ":" in v else v


if mode == "plan":
    import apt

    cache = apt.Cache()
    downloadable, missing = [], []
    by_site = collections.defaultdict(list)
    for p in cache:
        if not p.is_installed:
            continue
        v = p.installed
        site = (v.origins[0].site if v.origins else "") or "local .deb (no repo)"
        by_site[site].append(p.name)
        if v.downloadable:
            downloadable.append(f"{p.name}={v.version}")
        else:
            missing.append(f"{p.name}\t{v.version}\tinstalled version is not in any configured repo index")

    with open(os.path.join(lists, "downloadable.txt"), "w") as f:
        f.write("\n".join(sorted(downloadable)) + "\n")
    with open(os.path.join(lists, "not-downloadable.tsv"), "w") as f:
        f.write("package\tversion\treason\n" + "\n".join(sorted(missing)) + "\n")
    with open(os.path.join(lists, "by-repo.txt"), "w") as f:
        for site, pkgs in sorted(by_site.items(), key=lambda x: -len(x[1])):
            f.write(f"{len(pkgs):5}  {site}\n")
            if "ubuntu.com" not in site:
                f.write("       " + " ".join(sorted(pkgs)) + "\n")
    print(f"plan: {len(downloadable)} downloadable, {len(missing)} not in any repo")

elif mode == "verify":
    got = set()
    for fn in os.listdir(os.path.join(dest, "debs")):
        if fn.endswith(".deb"):
            name, ver, _ = fn[:-4].split("_", 2)
            got.add((name, noepoch(urllib.parse.unquote(ver))))
    failed = []
    with open(os.path.join(lists, "downloadable.txt")) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            name, ver = line.split("=", 1)
            if (name, noepoch(ver)) not in got:
                failed.append(f"{name}\t{ver}\tdownload failed (see download.log)")
    with open(os.path.join(lists, "download-failed.tsv"), "w") as f:
        f.write("package\tversion\treason\n" + "\n".join(failed) + ("\n" if failed else ""))
    print(f"verify: {len(got)} .deb files, {len(failed)} downloadable packages failed to fetch")
