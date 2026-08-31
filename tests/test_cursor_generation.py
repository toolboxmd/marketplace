#!/usr/bin/env python3
"""Cursor distribution tests at the complete generation-command seam."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATE = ROOT / "scripts" / "render_cursor.py"
FIXTURE = ROOT / "tests" / "fixtures" / "project-record-v1"


def _run(
    *args: str,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-08-31T12:00:00Z",
        "GIT_COMMITTER_DATE": "2026-08-31T12:00:00Z",
    }
    return subprocess.run(
        [*args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env=environment,
    )


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _prepare(temp: Path) -> tuple[Path, Path, str, str]:
    source = temp / "fixture-agent"
    marketplace = temp / "marketplace"
    shutil.copytree(FIXTURE, source)
    marketplace.mkdir()

    _run("git", "init", "-q", cwd=source)
    _run("git", "config", "user.name", "Fixture", cwd=source)
    _run("git", "config", "user.email", "fixture@example.com", cwd=source)
    _run("git", "add", ".", cwd=source)
    _run("git", "commit", "-q", "-m", "fixture release", cwd=source)
    _run("git", "tag", "-a", "v1.2.3", "-m", "fixture v1.2.3", cwd=source)

    commit = _run("git", "rev-parse", "v1.2.3^{}", cwd=source).stdout.strip()
    record_bytes = _run(
        "git",
        "show",
        f"{commit}:.toolboxmd/project.json",
        cwd=source,
    ).stdout.encode()
    digest = hashlib.sha256(record_bytes).hexdigest()
    catalog = {
        "name": "toolboxmd",
        "displayName": "toolbox.md",
        "description": "Skills and plugins from toolbox.md.",
        "owner": {"name": "lukaszmaj"},
        "plugins": [
            {
                "name": "fixture-agent",
                "description": "Coordinate fixture work through one trusted agent workflow.",
                "github": "toolboxmd/fixture-agent",
                "release": "v1.2.3",
                "sha": commit,
                "category": "Developer Tools",
                "kind": "agent-module",
                "projectRecord": {
                    "path": ".toolboxmd/project.json",
                    "sha256": digest,
                },
            }
        ],
    }
    (marketplace / "catalog.json").write_text(
        json.dumps(catalog, indent=2) + "\n",
        encoding="utf-8",
    )
    return source, marketplace, commit, digest


def _retag_and_accept(source: Path, marketplace: Path, message: str) -> None:
    _run("git", "tag", "-d", "v1.2.3", cwd=source)
    _run("git", "add", "-A", cwd=source)
    _run("git", "commit", "-q", "-m", message, cwd=source)
    _run("git", "tag", "-a", "v1.2.3", "-m", message, cwd=source)
    commit = _run("git", "rev-parse", "v1.2.3^{}", cwd=source).stdout.strip()
    record = _run(
        "git",
        "show",
        f"{commit}:.toolboxmd/project.json",
        cwd=source,
    ).stdout.encode()
    catalog = _json(marketplace / "catalog.json")
    catalog["plugins"][0]["sha"] = commit
    catalog["plugins"][0]["projectRecord"]["sha256"] = hashlib.sha256(
        record
    ).hexdigest()
    (marketplace / "catalog.json").write_text(
        json.dumps(catalog, indent=2) + "\n",
        encoding="utf-8",
    )


class CursorGenerationTests(unittest.TestCase):
    def test_complete_command_generates_exact_repeatable_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, marketplace, commit, digest = _prepare(Path(tmp))
            command = (
                sys.executable,
                str(GENERATE),
                "fixture-agent",
                "--source",
                str(source),
                "--marketplace-root",
                str(marketplace),
            )

            result = _run(*command, cwd=ROOT)
            first_hashes = _tree_hashes(marketplace)
            repeat = _run(*command, cwd=ROOT)

            plugin = marketplace / "plugins" / "fixture-agent"
            manifest = _json(plugin / ".cursor-plugin" / "plugin.json")
            marketplace_manifest = _json(
                marketplace / ".cursor-plugin" / "marketplace.json"
            )
            provenance = _json(plugin / "SOURCE.json")
            actual = {
                "result": json.loads(result.stdout),
                "repeat": json.loads(repeat.stdout),
                "repeatHashes": _tree_hashes(marketplace),
                "manifest": manifest,
                "marketplace": marketplace_manifest,
                "skillBytes": (plugin / "skills" / "example" / "SKILL.md").read_bytes(),
                "resourceBytes": (
                    plugin / "skills" / "example" / "reference.md"
                ).read_bytes(),
                "provenance": {
                    "project": provenance["project"],
                    "release": provenance["release"],
                    "commit": provenance["commit"],
                    "record": provenance["projectRecord"],
                    "sourcePaths": [item["source"] for item in provenance["files"]],
                },
            }
            expected = {
                "result": {
                    "project": "fixture-agent",
                    "release": "v1.2.3",
                    "commit": commit,
                    "recordSha256": digest,
                    "skills": ["fixture-example"],
                },
                "repeat": {
                    "project": "fixture-agent",
                    "release": "v1.2.3",
                    "commit": commit,
                    "recordSha256": digest,
                    "skills": ["fixture-example"],
                },
                "repeatHashes": first_hashes,
                "manifest": {
                    "name": "fixture-agent",
                    "displayName": "Fixture Agent",
                    "version": "1.2.3",
                    "description": "Coordinate fixture work through one trusted agent workflow.",
                    "author": {"name": "Fixture Maintainer"},
                    "homepage": "https://github.com/toolboxmd/fixture-agent#readme",
                    "repository": "https://github.com/toolboxmd/fixture-agent",
                    "license": "MIT",
                    "keywords": ["fixture", "workflow"],
                    "skills": "./skills/",
                },
                "marketplace": {
                    "name": "toolboxmd",
                    "owner": {"name": "lukaszmaj"},
                    "metadata": {
                        "description": "Skills and plugins from toolbox.md."
                    },
                    "plugins": [
                        {
                            "name": "fixture-agent",
                            "source": "./plugins/fixture-agent",
                            "description": "Coordinate fixture work through one trusted agent workflow.",
                            "version": "1.2.3",
                        }
                    ],
                },
                "skillBytes": (FIXTURE / "skills" / "example" / "SKILL.md").read_bytes(),
                "resourceBytes": (
                    FIXTURE / "skills" / "example" / "reference.md"
                ).read_bytes(),
                "provenance": {
                    "project": "fixture-agent",
                    "release": "v1.2.3",
                    "commit": commit,
                    "record": {
                        "path": ".toolboxmd/project.json",
                        "sha256": digest,
                    },
                    "sourcePaths": [
                        ".toolboxmd/project.json",
                        "LICENSE",
                        "VERSION",
                        "skills/example/SKILL.md",
                        "skills/example/reference.md",
                    ],
                },
            }
            self.assertEqual(actual, expected)

    def test_rejected_candidate_preserves_generated_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, marketplace, _, _ = _prepare(Path(tmp))
            command = (
                sys.executable,
                str(GENERATE),
                "fixture-agent",
                "--source",
                str(source),
                "--marketplace-root",
                str(marketplace),
            )
            _run(*command, cwd=ROOT)
            before = _tree_hashes(marketplace)

            catalog = _json(marketplace / "catalog.json")
            catalog["plugins"][0]["projectRecord"]["sha256"] = "0" * 64
            (marketplace / "catalog.json").write_text(
                json.dumps(catalog, indent=2) + "\n",
                encoding="utf-8",
            )
            catalog_hash = hashlib.sha256(
                (marketplace / "catalog.json").read_bytes()
            ).hexdigest()

            result = _run(*command, cwd=ROOT, check=False)
            after = _tree_hashes(marketplace)
            expected = {
                **before,
                "catalog.json": catalog_hash,
            }
            self.assertEqual(result.returncode, 2)
            self.assertTrue(result.stderr.startswith("Cursor generation rejected:"))
            self.assertEqual(after, expected)

    def test_every_rejected_source_preserves_generated_output(self) -> None:
        cases = (
            "missing-required-file",
            "release-version-mismatch",
            "invalid-manifest-path",
            "unsupported-component",
            "record-path-escape",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                source, marketplace, _, _ = _prepare(Path(tmp))
                command = (
                    sys.executable,
                    str(GENERATE),
                    "fixture-agent",
                    "--source",
                    str(source),
                    "--marketplace-root",
                    str(marketplace),
                )
                _run(*command, cwd=ROOT)
                before = _tree_hashes(marketplace)

                if case == "missing-required-file":
                    (source / "LICENSE").unlink()
                elif case == "release-version-mismatch":
                    (source / "VERSION").write_text("9.9.9\n", encoding="utf-8")
                elif case in {"invalid-manifest-path", "unsupported-component"}:
                    path = source / ".codex-plugin" / "plugin.json"
                    manifest = _json(path)
                    if case == "invalid-manifest-path":
                        manifest["skills"] = "../skills"
                    else:
                        manifest["hooks"] = "./hooks/hooks.json"
                    path.write_text(
                        json.dumps(manifest, indent=2) + "\n",
                        encoding="utf-8",
                    )
                elif case == "record-path-escape":
                    path = source / ".toolboxmd" / "project.json"
                    record = _json(path)
                    record["factSources"]["skills"] = ["../SKILL.md"]
                    path.write_text(
                        json.dumps(record, indent=2) + "\n",
                        encoding="utf-8",
                    )
                else:
                    self.fail(f"unknown case: {case}")
                _retag_and_accept(source, marketplace, f"invalid: {case}")
                catalog_hash = hashlib.sha256(
                    (marketplace / "catalog.json").read_bytes()
                ).hexdigest()

                result = _run(*command, cwd=ROOT, check=False)
                expected = {**before, "catalog.json": catalog_hash}
                self.assertEqual(result.returncode, 2)
                self.assertTrue(
                    result.stderr.startswith("Cursor generation rejected:"),
                    result.stderr,
                )
                self.assertEqual(_tree_hashes(marketplace), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
