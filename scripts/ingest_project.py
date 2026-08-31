#!/usr/bin/env python3
"""Ingest one released Project Record into accepted Marketplace state."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Iterator

from render_catalog import published_documents

ROOT = Path(__file__).resolve().parents[1]
RECORD_PATH = ".toolboxmd/project.json"
SCHEMA_ID = (
    "https://raw.githubusercontent.com/toolboxmd/marketplace/"
    "v0.3.0/schemas/project-record-v1.schema.json"
)
PROJECT_KEYS = {"$schema", "id", "kind", "outcome", "factSources"}
FACT_SOURCE_KEYS = {
    "version",
    "delivery",
    "skills",
    "documentation",
    "requirements",
    "proof",
}
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
PROJECT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class IngestionError(RuntimeError):
    """The candidate release cannot become accepted Marketplace state."""


def _git(source: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise IngestionError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _safe_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise IngestionError("Project Record paths must be non-empty strings")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise IngestionError(f"Project Record path escapes the release tree: {value}")
    return value


def _json_bytes(data: dict) -> bytes:
    return (json.dumps(data, indent=2) + "\n").encode("utf-8")


def _read_tree_bytes(source: Path, commit: str, relative_path: str) -> bytes:
    path = _safe_path(relative_path)
    result = subprocess.run(
        ["git", "-C", str(source), "show", f"{commit}:{path}"],
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise IngestionError(f"missing released file {path}: {detail}")
    return result.stdout


def _read_tree_json(source: Path, commit: str, relative_path: str) -> dict:
    raw = _read_tree_bytes(source, commit, relative_path)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IngestionError(f"malformed JSON in {relative_path}: {error}") from error
    if not isinstance(value, dict):
        raise IngestionError(f"expected a JSON object in {relative_path}")
    return value


def _path_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise IngestionError(f"factSources.{field} must be a non-empty list")
    paths = [_safe_path(item) for item in value]
    if len(paths) != len(set(paths)):
        raise IngestionError(f"factSources.{field} contains duplicate paths")
    return paths


def _validate_record(record: dict, project_id: str) -> dict:
    if set(record) != PROJECT_KEYS:
        raise IngestionError(
            "Project Record must contain only $schema, id, kind, outcome, and factSources"
        )
    if record["$schema"] != SCHEMA_ID:
        raise IngestionError(f"unsupported Project Record schema: {record['$schema']}")
    if record["id"] != project_id:
        raise IngestionError(
            f"Project Record id {record['id']!r} does not match {project_id!r}"
        )
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise IngestionError(f"invalid Project id: {project_id!r}")
    if record["kind"] != "agent-module":
        raise IngestionError(f"unsupported Project kind: {record['kind']!r}")
    if not isinstance(record["outcome"], str) or not record["outcome"].strip():
        raise IngestionError("Project Record outcome must be a non-empty string")

    sources = record["factSources"]
    if not isinstance(sources, dict):
        raise IngestionError("factSources must be an object")
    if set(sources) - FACT_SOURCE_KEYS:
        raise IngestionError("factSources contains unsupported fields")
    if not {"version", "delivery", "documentation"} <= set(sources):
        raise IngestionError(
            "factSources must contain version, delivery, and documentation"
        )
    _safe_path(sources["version"])
    delivery = sources["delivery"]
    if not isinstance(delivery, dict) or not delivery:
        raise IngestionError("factSources.delivery must be a non-empty object")
    for host, path in delivery.items():
        if not isinstance(host, str) or not host:
            raise IngestionError("delivery host names must be non-empty strings")
        _safe_path(path)
    for field in ("skills", "documentation", "requirements", "proof"):
        if field in sources:
            _path_list(sources[field], field)
    return sources


def _resolve_commit(source: Path, release: str) -> str:
    _git(source, "show-ref", "--verify", f"refs/tags/{release}")
    commit = _git(source, "rev-parse", f"refs/tags/{release}^{{commit}}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise IngestionError(f"release did not resolve to a full commit: {release}")
    return commit


def _load_candidate(
    source: Path,
    project_id: str,
    release: str,
) -> tuple[dict, str, str]:
    commit = _resolve_commit(source, release)
    record_bytes = _read_tree_bytes(source, commit, RECORD_PATH)
    try:
        record = json.loads(record_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IngestionError(f"malformed JSON in {RECORD_PATH}: {error}") from error
    if not isinstance(record, dict):
        raise IngestionError("Project Record must be a JSON object")
    sources = _validate_record(record, project_id)

    version_path = _safe_path(sources["version"])
    try:
        version = _read_tree_bytes(source, commit, version_path).decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise IngestionError(f"version source is not UTF-8: {version_path}") from error
    if not VERSION_RE.fullmatch(version):
        raise IngestionError(f"invalid released version: {version!r}")
    if release != f"v{version}":
        raise IngestionError(
            f"release ref {release!r} does not match version source {version!r}"
        )

    for path in sources["delivery"].values():
        manifest = _read_tree_json(source, commit, path)
        if manifest.get("name") != project_id:
            raise IngestionError(f"delivery identity mismatch in {path}")
        if manifest.get("version") != version:
            raise IngestionError(f"delivery version mismatch in {path}")

    for field in ("skills", "documentation", "requirements", "proof"):
        for path in sources.get(field, []):
            _read_tree_bytes(source, commit, path)

    digest = hashlib.sha256(record_bytes).hexdigest()
    return record, commit, digest


@contextlib.contextmanager
def _release_source(github: str, supplied: Path | None) -> Iterator[Path]:
    if supplied is not None:
        yield supplied.resolve()
        return
    with tempfile.TemporaryDirectory(prefix="toolboxmd-project-") as tmp:
        source = Path(tmp) / "source"
        result = subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--filter=blob:none",
                "--no-checkout",
                f"https://github.com/{github}.git",
                str(source),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise IngestionError(result.stderr.strip() or "git clone failed")
        yield source


def _accepted_outputs(catalog: dict) -> dict[str, bytes]:
    outputs = {"catalog.json": _json_bytes(catalog)}
    outputs.update(
        {
            path: _json_bytes(document)
            for path, document in published_documents(catalog).items()
        }
    )
    return outputs


def _write_outputs(root: Path, outputs: dict[str, bytes]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ingest-", dir=root) as tmp:
        stage = Path(tmp)
        for relative_path, content in outputs.items():
            destination = stage / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        for relative_path in outputs:
            destination = root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / relative_path, destination)


def ingest(
    marketplace_root: Path,
    project_id: str,
    release: str,
    supplied_source: Path | None,
) -> dict:
    catalog_path = marketplace_root / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    matches = [item for item in catalog.get("plugins", []) if item.get("name") == project_id]
    if len(matches) != 1:
        raise IngestionError(f"Project is not uniquely curated: {project_id}")
    current = matches[0]
    github = current.get("github")
    if not isinstance(github, str) or not github:
        raise IngestionError(f"curated Project has no GitHub source: {project_id}")

    with _release_source(github, supplied_source) as source:
        record, commit, digest = _load_candidate(source, project_id, release)

    entry = next(item for item in catalog["plugins"] if item["name"] == project_id)
    entry["description"] = record["outcome"].strip()
    entry["kind"] = record["kind"]
    entry["release"] = release
    entry["sha"] = commit
    entry["projectRecord"] = {"path": RECORD_PATH, "sha256": digest}
    _write_outputs(marketplace_root, _accepted_outputs(catalog))
    return {
        "project": project_id,
        "release": release,
        "commit": commit,
        "recordSha256": digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="Curated Project id from catalog.json")
    parser.add_argument("release", help="Exact immutable release tag")
    parser.add_argument(
        "--source",
        type=Path,
        help="Local Git source for deterministic acceptance; defaults to curated GitHub",
    )
    parser.add_argument(
        "--marketplace-root",
        type=Path,
        default=ROOT,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    try:
        result = ingest(
            args.marketplace_root.resolve(),
            args.project,
            args.release,
            args.source,
        )
    except (IngestionError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ingestion rejected: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
