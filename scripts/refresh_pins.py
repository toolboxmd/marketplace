#!/usr/bin/env python3
"""Update catalog.json plugin SHAs from each GitHub default branch, then re-render."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "catalog.json"
RENDER = ROOT / "scripts" / "render_catalog.py"


def ls_remote_sha(github: str) -> str:
    url = f"https://github.com/{github}.git"
    result = subprocess.run(
        ["git", "ls-remote", url, "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    sha = result.stdout.split()[0].strip()
    if len(sha) != 40:
        raise SystemExit(f"unexpected sha for {github}: {sha!r}")
    return sha


def main() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    changed = False
    for plugin in catalog["plugins"]:
        sha = ls_remote_sha(plugin["github"])
        if plugin.get("sha") != sha:
            print(f"{plugin['name']}: {plugin.get('sha', '-')} -> {sha}")
            plugin["sha"] = sha
            changed = True
        else:
            print(f"{plugin['name']}: {sha} (unchanged)")
    if changed:
        CATALOG_PATH.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(RENDER)], check=True)


if __name__ == "__main__":
    main()
