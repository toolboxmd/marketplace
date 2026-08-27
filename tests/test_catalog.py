#!/usr/bin/env python3
"""Catalog indexes must name toolboxmd and list the same plugins on every host."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PLUGIN_NAMES = ("karpathy-wiki", "use-grok", "agentsmd")


def _load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _plugin_names(index: dict) -> list[str]:
    return [plugin["name"] for plugin in index.get("plugins", [])]


def _outside_root(path: str) -> bool:
    return not path.startswith("./") or ".." in Path(path).parts


class PublishedCatalogTests(unittest.TestCase):
    def test_catalog_membership(self) -> None:
        self.assertEqual(CATALOG["name"], "toolboxmd")
        self.assertEqual(CATALOG["displayName"], "toolbox.md")
        self.assertEqual(tuple(p["name"] for p in CATALOG["plugins"]), PLUGIN_NAMES)

    def test_host_indexes_agree(self) -> None:
        codex = _load(".agents/plugins/marketplace.json")
        claude = _load(".claude-plugin/marketplace.json")
        grok = _load(".grok-plugin/marketplace.json")
        for index in (codex, claude, grok):
            self.assertEqual(index["name"], "toolboxmd")
            self.assertEqual(tuple(_plugin_names(index)), PLUGIN_NAMES)
        self.assertEqual(codex.get("interface", {}).get("displayName"), "toolbox.md")

    def test_published_sources_are_legal(self) -> None:
        codex = _load(".agents/plugins/marketplace.json")
        claude = _load(".claude-plugin/marketplace.json")
        grok = _load(".grok-plugin/marketplace.json")
        by_name = {p["name"]: p for p in CATALOG["plugins"]}

        for plugin in codex["plugins"]:
            source = plugin["source"]
            self.assertEqual(source["source"], "url")
            self.assertEqual(
                source["url"],
                f"https://github.com/{by_name[plugin['name']]['github']}.git",
            )
            self.assertFalse(_outside_root(source.get("path", "./ok")))

        for plugin in claude["plugins"]:
            source = plugin["source"]
            self.assertEqual(source["source"], "github")
            self.assertEqual(source["repo"], by_name[plugin["name"]]["github"])

        for plugin in grok["plugins"]:
            source = plugin["source"]
            self.assertEqual(source["source"], "url")
            self.assertEqual(
                source["url"],
                f"https://github.com/{by_name[plugin['name']]['github']}.git",
            )
            self.assertRegex(source["sha"], SHA_RE)
            self.assertEqual(source["sha"], by_name[plugin["name"]]["sha"])


class LocalCatalogTests(unittest.TestCase):
    def test_local_render_matches_published_names(self) -> None:
        render = ROOT / "scripts" / "render_catalog.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(
                [sys.executable, str(render), "--local-root", str(root)],
                check=True,
            )
            codex = json.loads(
                (root / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
            )
            claude = json.loads(
                (root / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
            )
            grok = json.loads(
                (root / ".grok-plugin/marketplace.json").read_text(encoding="utf-8")
            )
            for index in (codex, claude, grok):
                self.assertEqual(index["name"], "toolboxmd")
                self.assertEqual(tuple(_plugin_names(index)), PLUGIN_NAMES)
                for plugin in index["plugins"]:
                    source = plugin["source"]
                    if isinstance(source, str):
                        path = source
                    elif source.get("source") == "local" or source.get("type") == "local":
                        path = source["path"]
                    else:
                        path = source.get("path", "")
                    self.assertTrue(path.startswith("./"), path)
                    self.assertFalse(_outside_root(path), path)
                    self.assertEqual(path, f"./{plugin['name']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
