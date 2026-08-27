#!/usr/bin/env python3
"""Render host marketplace indexes from catalog.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "catalog.json"


def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def git_url(plugin: dict) -> str:
    return f"https://github.com/{plugin['github']}.git"


def published_codex(catalog: dict) -> dict:
    return {
        "name": catalog["name"],
        "interface": {"displayName": catalog["displayName"]},
        "plugins": [
            {
                "name": plugin["name"],
                "description": plugin["description"],
                "source": {"source": "url", "url": git_url(plugin)},
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": plugin["category"],
            }
            for plugin in catalog["plugins"]
        ],
    }


def published_claude(catalog: dict) -> dict:
    return {
        "name": catalog["name"],
        "owner": catalog["owner"],
        "metadata": {"description": catalog["description"]},
        "plugins": [
            {
                "name": plugin["name"],
                "description": plugin["description"],
                "source": {"source": "github", "repo": plugin["github"]},
            }
            for plugin in catalog["plugins"]
        ],
    }


def published_grok(catalog: dict) -> dict:
    return {
        "name": catalog["name"],
        "description": catalog["description"],
        "owner": catalog["owner"],
        "plugins": [
            {
                "name": plugin["name"],
                "description": plugin["description"],
                "category": plugin.get("category", "development").lower().replace(" ", "-"),
                "source": {
                    "source": "url",
                    "url": git_url(plugin),
                    "sha": plugin["sha"],
                },
                "homepage": f"https://github.com/{plugin['github']}",
            }
            for plugin in catalog["plugins"]
        ],
    }


def local_codex(catalog: dict) -> dict:
    return {
        "name": catalog["name"],
        "interface": {"displayName": catalog["displayName"]},
        "plugins": [
            {
                "name": plugin["name"],
                "source": {"source": "local", "path": f"./{plugin['name']}"},
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": plugin["category"],
            }
            for plugin in catalog["plugins"]
        ],
    }


def local_claude(catalog: dict) -> dict:
    return {
        "name": catalog["name"],
        "owner": catalog["owner"],
        "metadata": {"description": catalog["description"]},
        "plugins": [
            {
                "name": plugin["name"],
                "description": plugin["description"],
                "source": f"./{plugin['name']}",
            }
            for plugin in catalog["plugins"]
        ],
    }


def local_grok(catalog: dict) -> dict:
    return {
        "name": catalog["name"],
        "description": catalog["description"],
        "owner": catalog["owner"],
        "plugins": [
            {
                "name": plugin["name"],
                "description": plugin["description"],
                "source": {"type": "local", "path": f"./{plugin['name']}"},
            }
            for plugin in catalog["plugins"]
        ],
    }


def render_published(catalog: dict) -> None:
    dump(ROOT / ".agents/plugins/marketplace.json", published_codex(catalog))
    dump(ROOT / ".claude-plugin/marketplace.json", published_claude(catalog))
    dump(ROOT / ".grok-plugin/marketplace.json", published_grok(catalog))


def render_local(catalog: dict, local_root: Path) -> None:
    dump(local_root / ".agents/plugins/marketplace.json", local_codex(catalog))
    dump(local_root / ".claude-plugin/marketplace.json", local_claude(catalog))
    dump(local_root / ".grok-plugin/marketplace.json", local_grok(catalog))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local-root",
        type=Path,
        help="Write sibling-checkout indexes here instead of published GitHub sources",
    )
    args = parser.parse_args()
    catalog = load_catalog()
    if args.local_root:
        render_local(catalog, args.local_root.resolve())
    else:
        render_published(catalog)


if __name__ == "__main__":
    main()
