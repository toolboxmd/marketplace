#!/usr/bin/env python3
"""Catalog indexes must name toolboxmd and list the same plugins on every host."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REFRESH_SPEC = importlib.util.spec_from_file_location(
    "marketplace_refresh_pins", ROOT / "scripts" / "refresh_pins.py"
)
assert REFRESH_SPEC and REFRESH_SPEC.loader
refresh_pins = importlib.util.module_from_spec(REFRESH_SPEC)
REFRESH_SPEC.loader.exec_module(refresh_pins)
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
            catalog_plugin = by_name[plugin["name"]]
            self.assertEqual(source["source"], "url")
            self.assertEqual(
                source["url"],
                f"https://github.com/{catalog_plugin['github']}.git",
            )
            self.assertEqual(source["sha"], catalog_plugin["sha"])
            if release := catalog_plugin.get("release"):
                self.assertEqual(source["ref"], release)
            else:
                self.assertNotIn("ref", source)
            self.assertFalse(_outside_root(source.get("path", "./ok")))

        for plugin in claude["plugins"]:
            source = plugin["source"]
            catalog_plugin = by_name[plugin["name"]]
            self.assertEqual(source["source"], "github")
            self.assertEqual(source["repo"], catalog_plugin["github"])
            self.assertEqual(source["sha"], catalog_plugin["sha"])
            if release := catalog_plugin.get("release"):
                self.assertEqual(source["ref"], release)
            else:
                self.assertNotIn("ref", source)

        for plugin in grok["plugins"]:
            source = plugin["source"]
            self.assertEqual(source["source"], "url")
            self.assertEqual(
                source["url"],
                f"https://github.com/{by_name[plugin['name']]['github']}.git",
            )
            self.assertRegex(source["sha"], SHA_RE)
            self.assertEqual(source["sha"], by_name[plugin["name"]]["sha"])

    def test_agentsmd_project_record_publication(self) -> None:
        agentsmd_sha = "8d4b528e6be9841288665424de4ba9f16c4a58f3"
        agentsmd_description = (
            "Align agent work with mission and Project Direction, then shape, "
            "deliver, and prove valuable outcomes through owned workflows."
        )
        by_name = {p["name"]: p for p in CATALOG["plugins"]}

        self.assertEqual(by_name["agentsmd"]["release"], "v6.0.0")
        self.assertEqual(by_name["agentsmd"]["sha"], agentsmd_sha)
        self.assertEqual(by_name["agentsmd"]["description"], agentsmd_description)
        self.assertEqual(by_name["agentsmd"]["kind"], "agent-module")
        self.assertEqual(
            by_name["agentsmd"]["projectRecord"],
            {
                "path": ".toolboxmd/project.json",
                "sha256": (
                    "470d247d853f8ccd93bafb9ced45a3cb"
                    "5e7eb22ab8371d6e6d9a7519ddfb323a"
                ),
            },
        )
        self.assertEqual(
            by_name["use-grok"]["sha"],
            "a8ae6ab3c862de836ca576276a221610e3fe274c",
        )
        self.assertEqual(
            by_name["karpathy-wiki"]["sha"],
            "d8107e727f4b585a9927cad813f90fda6b559ef3",
        )

        for index_path, records_release in (
            (".agents/plugins/marketplace.json", True),
            (".claude-plugin/marketplace.json", True),
            (".grok-plugin/marketplace.json", False),
        ):
            index = _load(index_path)
            agentsmd = next(p for p in index["plugins"] if p["name"] == "agentsmd")
            self.assertEqual(agentsmd["description"], agentsmd_description)
            self.assertEqual(agentsmd["source"]["sha"], agentsmd_sha)
            if records_release:
                self.assertEqual(agentsmd["source"]["ref"], "v6.0.0")
            else:
                self.assertNotIn("ref", agentsmd["source"])


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


class RefreshPinTests(unittest.TestCase):
    @patch.object(refresh_pins.subprocess, "run")
    def test_annotated_release_resolves_to_peeled_commit(self, run) -> None:
        release_commit = "b80dbf425bac2208992702f824950c8cba466fef"
        run.return_value = SimpleNamespace(
            stdout=(
                "217ba7ee7aba3290e16b221562581fbc200b41d8\t"
                "refs/tags/v5.0.0\n"
                f"{release_commit}\trefs/tags/v5.0.0^{{}}\n"
            )
        )

        self.assertEqual(
            refresh_pins.ls_remote_sha("toolboxmd/agentsmd", "v5.0.0"),
            release_commit,
        )
        run.assert_called_once_with(
            [
                "git",
                "ls-remote",
                "https://github.com/toolboxmd/agentsmd.git",
                "refs/tags/v5.0.0",
                "refs/tags/v5.0.0^{}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
