#!/usr/bin/env python3
"""Project Record ingestion tests at the complete command seam."""

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
INGEST = ROOT / "scripts" / "ingest_project.py"
FIXTURE = ROOT / "tests" / "fixtures" / "project-record-v1"
INDEX_PATHS = (
    ".agents/plugins/marketplace.json",
    ".claude-plugin/marketplace.json",
    ".grok-plugin/marketplace.json",
)
ACCEPTED_PATHS = ("catalog.json", *INDEX_PATHS)
RECORD_DIGEST = "4f694176080285495aab1ba1d9891ce085e7df7ac459463a0b24f9376026903c"


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-08-31T12:00:00Z",
        "GIT_COMMITTER_DATE": "2026-08-31T12:00:00Z",
    }
    return subprocess.run(
        [*args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _accepted_hashes(root: Path) -> dict[str, str]:
    return {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
        for path in ACCEPTED_PATHS
    }


def _entry(document: dict, project_id: str) -> dict:
    return next(item for item in document["plugins"] if item["name"] == project_id)


def _prepare_fixture(
    temp: Path,
    description: str,
) -> tuple[Path, Path]:
    source = temp / "fixture-agent"
    marketplace = temp / "marketplace"
    shutil.copytree(FIXTURE, source)
    marketplace.mkdir()

    for path in ACCEPTED_PATHS:
        destination = marketplace / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, destination)

    catalog = _load(marketplace / "catalog.json")
    catalog["plugins"].append(
        {
            "name": "fixture-agent",
            "description": description,
            "github": "toolboxmd/fixture-agent",
            "sha": "0" * 40,
            "category": "Developer Tools",
        }
    )
    (marketplace / "catalog.json").write_text(
        json.dumps(catalog, indent=2) + "\n",
        encoding="utf-8",
    )
    return source, marketplace


def _commit_fixture(source: Path, release: str, message: str) -> None:
    _run("git", "init", "-q", cwd=source)
    _run("git", "config", "user.name", "Fixture", cwd=source)
    _run("git", "config", "user.email", "fixture@example.com", cwd=source)
    _run("git", "add", ".", cwd=source)
    _run("git", "commit", "-q", "-m", message, cwd=source)
    _run("git", "tag", "-a", release, "-m", f"fixture {release}", cwd=source)


class ProjectRecordIngestionTests(unittest.TestCase):
    def test_schema_is_a_minimal_pointer_contract(self) -> None:
        schema = _load(ROOT / "schemas" / "project-record-v1.schema.json")
        record = _load(FIXTURE / ".toolboxmd" / "project.json")
        fact_schema = schema["$defs"]["factSources"]
        actual = {
            "schemaId": schema["$id"],
            "schemaConst": schema["properties"]["$schema"]["const"],
            "recordRequired": schema["required"],
            "recordFields": list(schema["properties"]),
            "kindContract": schema["properties"]["kind"],
            "factRequired": fact_schema["required"],
            "factFields": list(fact_schema["properties"]),
            "fixtureFields": list(record),
            "fixtureFactFields": list(record["factSources"]),
        }
        expected = {
            "schemaId": (
                "https://raw.githubusercontent.com/toolboxmd/marketplace/"
                "v0.3.0/schemas/project-record-v1.schema.json"
            ),
            "schemaConst": (
                "https://raw.githubusercontent.com/toolboxmd/marketplace/"
                "v0.3.0/schemas/project-record-v1.schema.json"
            ),
            "recordRequired": ["$schema", "id", "kind", "outcome", "factSources"],
            "recordFields": ["$schema", "id", "kind", "outcome", "factSources"],
            "kindContract": {"const": "agent-module"},
            "factRequired": ["version", "delivery", "documentation"],
            "factFields": [
                "version",
                "delivery",
                "skills",
                "documentation",
                "requirements",
                "proof",
            ],
            "fixtureFields": ["$schema", "id", "kind", "outcome", "factSources"],
            "fixtureFactFields": [
                "version",
                "delivery",
                "skills",
                "documentation",
                "proof",
            ],
        }
        self.assertEqual(actual, expected)

    def test_complete_ingestion_publishes_one_release_consistently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            source, marketplace = _prepare_fixture(
                temp,
                "Stale fixture description.",
            )
            _commit_fixture(source, "v1.2.3", "fixture release")
            release_commit = _run(
                "git", "rev-parse", "v1.2.3^{}", cwd=source
            ).stdout.strip()

            command = (
                sys.executable,
                str(INGEST),
                "fixture-agent",
                "v1.2.3",
                "--source",
                str(source),
                "--marketplace-root",
                str(marketplace),
            )
            _run(*command, cwd=ROOT)

            catalog_entry = _entry(_load(marketplace / "catalog.json"), "fixture-agent")
            host_entries = {
                path: _entry(_load(marketplace / path), "fixture-agent")
                for path in INDEX_PATHS
            }
            first_hashes = _accepted_hashes(marketplace)
            _run(*command, cwd=ROOT)

            actual = {
                "catalog": catalog_entry,
                "codex": host_entries[INDEX_PATHS[0]],
                "claude": host_entries[INDEX_PATHS[1]],
                "grok": host_entries[INDEX_PATHS[2]],
                "repeatHashes": _accepted_hashes(marketplace),
            }
            expected = {
                "catalog": {
                    "name": "fixture-agent",
                    "description": "Coordinate fixture work through one trusted agent workflow.",
                    "kind": "agent-module",
                    "github": "toolboxmd/fixture-agent",
                    "release": "v1.2.3",
                    "sha": release_commit,
                    "category": "Developer Tools",
                    "projectRecord": {
                        "path": ".toolboxmd/project.json",
                        "sha256": RECORD_DIGEST,
                    },
                },
                "codex": {
                    "name": "fixture-agent",
                    "description": "Coordinate fixture work through one trusted agent workflow.",
                    "source": {
                        "source": "url",
                        "url": "https://github.com/toolboxmd/fixture-agent.git",
                        "sha": release_commit,
                        "ref": "v1.2.3",
                    },
                    "policy": {
                        "installation": "AVAILABLE",
                        "authentication": "ON_INSTALL",
                    },
                    "category": "Developer Tools",
                },
                "claude": {
                    "name": "fixture-agent",
                    "description": "Coordinate fixture work through one trusted agent workflow.",
                    "source": {
                        "source": "github",
                        "repo": "toolboxmd/fixture-agent",
                        "sha": release_commit,
                        "ref": "v1.2.3",
                    },
                },
                "grok": {
                    "name": "fixture-agent",
                    "description": "Coordinate fixture work through one trusted agent workflow.",
                    "category": "developer-tools",
                    "source": {
                        "source": "url",
                        "url": "https://github.com/toolboxmd/fixture-agent.git",
                        "sha": release_commit,
                    },
                    "homepage": "https://github.com/toolboxmd/fixture-agent",
                },
                "repeatHashes": first_hashes,
            }
            self.assertEqual(actual, expected)

    def test_every_rejection_preserves_accepted_state(self) -> None:
        def mutate_record(source: Path, key: str, value: object) -> None:
            path = source / ".toolboxmd" / "project.json"
            record = _load(path)
            record[key] = value
            path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

        def mutate_source(source: Path, case: str) -> str:
            release = "v1.2.3"
            if case == "missing-record":
                (source / ".toolboxmd" / "project.json").unlink()
            elif case == "unsupported-schema":
                mutate_record(source, "$schema", "https://example.com/unknown")
            elif case == "wrong-identity":
                mutate_record(source, "id", "another-project")
            elif case == "missing-reference":
                record = _load(source / ".toolboxmd" / "project.json")
                record["factSources"]["documentation"] = ["MISSING.md"]
                (source / ".toolboxmd" / "project.json").write_text(
                    json.dumps(record, indent=2) + "\n", encoding="utf-8"
                )
            elif case == "version-disagreement":
                manifest = source / ".codex-plugin" / "plugin.json"
                value = _load(manifest)
                value["version"] = "9.9.9"
                manifest.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            elif case == "malformed-manifest":
                (source / ".grok-plugin" / "plugin.json").write_text(
                    "{\n", encoding="utf-8"
                )
            elif case == "release-ref-mismatch":
                release = "v9.9.9"
            elif case == "path-escape":
                record = _load(source / ".toolboxmd" / "project.json")
                record["factSources"]["documentation"] = ["../README.md"]
                (source / ".toolboxmd" / "project.json").write_text(
                    json.dumps(record, indent=2) + "\n", encoding="utf-8"
                )
            else:
                self.fail(f"unknown case: {case}")
            return release

        cases = (
            "missing-record",
            "unsupported-schema",
            "wrong-identity",
            "missing-reference",
            "version-disagreement",
            "malformed-manifest",
            "release-ref-mismatch",
            "path-escape",
        )
        actual: dict[str, dict[str, object]] = {}

        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                temp = Path(tmp)
                source, marketplace = _prepare_fixture(
                    temp,
                    "Last known-good fixture.",
                )
                before = _accepted_hashes(marketplace)

                release = mutate_source(source, case)
                _commit_fixture(source, release, f"invalid fixture: {case}")

                result = subprocess.run(
                    [
                        sys.executable,
                        str(INGEST),
                        "fixture-agent",
                        release,
                        "--source",
                        str(source),
                        "--marketplace-root",
                        str(marketplace),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )
                actual[case] = {
                    "returncode": result.returncode,
                    "preserved": _accepted_hashes(marketplace) == before,
                    "reported": result.stderr.startswith("ingestion rejected:"),
                }

        expected = {
            case: {"returncode": 2, "preserved": True, "reported": True}
            for case in cases
        }
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
