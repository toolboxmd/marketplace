#!/usr/bin/env python3
"""Generate one Cursor Plugin from accepted Marketplace release state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ingest_project import (
    IngestionError,
    RECORD_PATH,
    _load_candidate,
    _read_tree_bytes,
    _read_tree_json,
    _release_source,
    _safe_path,
)

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
UNPROVED_COMPONENT_FIELDS = {
    "rules",
    "agents",
    "commands",
    "hooks",
    "mcpServers",
    "variables",
}
AGENTSMD_RUNTIME_PATHS = (
    "bin/versionctl",
    "tools/versionctl/bin/versionctl",
    "tools/versionctl/src",
)


class CursorGenerationError(RuntimeError):
    """The accepted release cannot become a valid Cursor distribution."""


@dataclass(frozen=True)
class SourceFile:
    source: str
    content: bytes
    mode: int


def _json_bytes(data: dict) -> bytes:
    return (json.dumps(data, indent=2) + "\n").encode("utf-8")


def _catalog_entry(catalog: dict, project_id: str) -> dict:
    matches = [item for item in catalog.get("plugins", []) if item.get("name") == project_id]
    if len(matches) != 1:
        raise CursorGenerationError(f"Project is not uniquely accepted: {project_id}")
    entry = matches[0]
    for field in ("github", "release", "sha", "projectRecord"):
        if field not in entry:
            raise CursorGenerationError(f"accepted Project is missing {field}: {project_id}")
    if not isinstance(entry["github"], str) or not entry["github"]:
        raise CursorGenerationError("accepted GitHub source must be a non-empty string")
    if not isinstance(entry["release"], str) or not entry["release"]:
        raise CursorGenerationError("accepted release must be a non-empty string")
    if not isinstance(entry["sha"], str) or not SHA_RE.fullmatch(entry["sha"]):
        raise CursorGenerationError("accepted release commit must be a full SHA-1")
    record = entry["projectRecord"]
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise CursorGenerationError("accepted projectRecord must contain path and sha256")
    if record["path"] != RECORD_PATH:
        raise CursorGenerationError(f"unsupported Project Record path: {record['path']!r}")
    if not isinstance(record["sha256"], str) or not DIGEST_RE.fullmatch(record["sha256"]):
        raise CursorGenerationError("accepted Project Record digest must be SHA-256")
    return entry


def _git_lines(source: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(source), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CursorGenerationError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.splitlines()


def _tree_entries(source: Path, commit: str, relative_path: str) -> list[tuple[str, int]]:
    path = _safe_path(relative_path)
    lines = _git_lines(source, "ls-tree", "-r", commit, "--", path)
    entries: list[tuple[str, int]] = []
    for line in lines:
        try:
            metadata, tree_path = line.split("\t", 1)
            mode_text, kind, _ = metadata.split(" ", 2)
        except ValueError as error:
            raise CursorGenerationError(f"malformed Git tree entry for {path}") from error
        safe_tree_path = _safe_path(tree_path)
        if kind != "blob" or mode_text not in {"100644", "100755"}:
            raise CursorGenerationError(
                f"unsupported released file type or mode: {safe_tree_path} ({mode_text} {kind})"
            )
        entries.append((safe_tree_path, int(mode_text, 8)))
    return entries


def _add_path(
    files: dict[str, SourceFile],
    source: Path,
    commit: str,
    relative_path: str,
) -> None:
    entries = _tree_entries(source, commit, relative_path)
    if not entries:
        raise CursorGenerationError(f"missing released package path: {relative_path}")
    for tree_path, mode in entries:
        if tree_path in files:
            continue
        files[tree_path] = SourceFile(
            source=tree_path,
            content=_read_tree_bytes(source, commit, tree_path),
            mode=mode,
        )


def _add_optional_path(
    files: dict[str, SourceFile],
    source: Path,
    commit: str,
    relative_path: str,
) -> None:
    if _tree_entries(source, commit, relative_path):
        _add_path(files, source, commit, relative_path)


def _frontmatter(content: bytes, path: str) -> dict[str, str]:
    try:
        text = content.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as error:
        raise CursorGenerationError(f"Skill is not UTF-8: {path}") from error
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise CursorGenerationError(f"Skill has no complete YAML frontmatter: {path}")
    block = text[4 : text.index("\n---\n", 4)]
    fields: dict[str, str] = {}
    current: str | None = None
    for line in block.splitlines():
        if line[:1].isspace() and current:
            fields[current] = f"{fields[current]} {line.strip()}".strip()
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current = key.strip()
        fields[current] = value.strip().strip('"\'')
    for required in ("name", "description"):
        if not fields.get(required):
            raise CursorGenerationError(f"Skill frontmatter lacks {required}: {path}")
    if not SKILL_NAME_RE.fullmatch(fields["name"]):
        raise CursorGenerationError(f"invalid Cursor Skill name in {path}: {fields['name']!r}")
    return fields


def _source_files(
    source: Path,
    commit: str,
    project_id: str,
    record: dict,
) -> tuple[dict[str, SourceFile], list[str]]:
    sources = record["factSources"]
    files: dict[str, SourceFile] = {}
    _add_path(files, source, commit, RECORD_PATH)
    _add_path(files, source, commit, sources["version"])
    _add_path(files, source, commit, "LICENSE")

    skill_names: list[str] = []
    for skill_path in sources.get("skills", []):
        path = PurePosixPath(_safe_path(skill_path))
        if len(path.parts) != 3 or path.parts[0] != "skills" or path.name != "SKILL.md":
            raise CursorGenerationError(
                f"Cursor Skills must use skills/<name>/SKILL.md: {skill_path}"
            )
        _add_path(files, source, commit, path.parent.as_posix())
        skill = _frontmatter(files[skill_path].content, skill_path)
        skill_names.append(skill["name"])

    for optional in ("THIRD_PARTY_NOTICES.md", "LICENSES", "provenance"):
        _add_optional_path(files, source, commit, optional)
    for documentation_path in sources.get("documentation", []):
        if PurePosixPath(documentation_path).name != "README.md":
            _add_path(files, source, commit, documentation_path)
    if project_id == "agentsmd":
        for runtime_path in AGENTSMD_RUNTIME_PATHS:
            _add_path(files, source, commit, runtime_path)

    if not skill_names:
        raise CursorGenerationError("released Project declares no Cursor Skills")
    if len(skill_names) != len(set(skill_names)):
        raise CursorGenerationError("released Project declares duplicate Cursor Skill names")
    return files, sorted(skill_names)


def _cursor_manifest(
    source: Path,
    commit: str,
    project_id: str,
    record: dict,
    version: str,
) -> tuple[dict, dict[str, str]]:
    delivery = record["factSources"]["delivery"]
    manifest_path = delivery.get("codex")
    if not isinstance(manifest_path, str):
        raise CursorGenerationError("Cursor adapter requires a released codex manifest owner")
    source_manifest = _read_tree_json(source, commit, manifest_path)
    unproved = sorted(UNPROVED_COMPONENT_FIELDS & set(source_manifest))
    if unproved:
        raise CursorGenerationError(
            "unproved source components cannot be mapped to Cursor: " + ", ".join(unproved)
        )
    if source_manifest.get("name") != project_id:
        raise CursorGenerationError("released manifest identity disagrees with Project Record")
    if source_manifest.get("version") != version:
        raise CursorGenerationError("released manifest version disagrees with version source")
    source_skills = source_manifest.get("skills")
    if source_skills is not None:
        try:
            safe_source_skills = _safe_path(source_skills)
        except IngestionError as error:
            raise CursorGenerationError(str(error)) from error
        if PurePosixPath(safe_source_skills) != PurePosixPath("skills"):
            raise CursorGenerationError(
                f"released Skill component path is unsupported: {source_skills!r}"
            )

    author = source_manifest.get("author")
    if not isinstance(author, dict) or not isinstance(author.get("name"), str):
        raise CursorGenerationError("released manifest must own author.name")
    license_id = source_manifest.get("license")
    if not isinstance(license_id, str) or not license_id:
        raise CursorGenerationError("released manifest must own a licence identifier")
    interface = source_manifest.get("interface", {})
    display_name = interface.get("displayName", project_id) if isinstance(interface, dict) else project_id
    if not isinstance(display_name, str) or not display_name:
        raise CursorGenerationError("released display name must be a non-empty string")
    keywords = source_manifest.get("keywords", [])
    if not isinstance(keywords, list) or not all(isinstance(item, str) for item in keywords):
        raise CursorGenerationError("released keywords must be an array of strings")

    manifest: dict[str, object] = {
        "name": project_id,
        "displayName": display_name,
        "version": version,
        "description": record["outcome"].strip(),
        "author": {"name": author["name"]},
    }
    for field in ("homepage", "repository"):
        value = source_manifest.get(field)
        if value is not None:
            if not isinstance(value, str) or not value.startswith("https://"):
                raise CursorGenerationError(f"released {field} must be an HTTPS URL")
            manifest[field] = value
    manifest["license"] = license_id
    if keywords:
        manifest["keywords"] = keywords
    manifest["skills"] = "./skills/"
    trace = {
        "name": RECORD_PATH,
        "displayName": manifest_path,
        "version": record["factSources"]["version"],
        "description": RECORD_PATH,
        "author": manifest_path,
        "homepage": manifest_path,
        "repository": manifest_path,
        "license": manifest_path,
        "keywords": manifest_path,
        "skills": RECORD_PATH,
    }
    return manifest, trace


def _readme(display_name: str, release: str, commit: str, repository: str) -> bytes:
    text = f"""# {display_name} for Cursor

This Cursor Plugin is generated by ToolboxMD Marketplace from [{release}]({repository}/tree/{release}) at commit `{commit}`.

It exposes the released workflow Skills through Cursor's native Skill discovery. It does not install a global `AGENTS.md` file and does not claim lifecycle-hook equivalence. Configure global instructions separately when required.

`SOURCE.json` records the Project Record digest, exact source commit, manifest field owners, and SHA-256 hash of every copied released file.
"""
    return text.encode("utf-8")


def _write_file(path: Path, content: bytes, mode: int = 0o100644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(stat.S_IMODE(mode))


def _validate_staged(stage: Path, project_id: str, skill_names: list[str]) -> None:
    marketplace = json.loads(
        (stage / ".cursor-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    plugin_entry = marketplace["plugins"][0]
    expected_source = f"./plugins/{project_id}"
    if plugin_entry.get("source") != expected_source:
        raise CursorGenerationError("generated Cursor marketplace source is invalid")
    if ".." in PurePosixPath(expected_source).parts:
        raise CursorGenerationError("generated Cursor marketplace source escapes the repository")

    plugin = stage / "plugins" / project_id
    manifest = json.loads(
        (plugin / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    if manifest.get("name") != project_id or manifest.get("skills") != "./skills/":
        raise CursorGenerationError("generated Cursor Plugin manifest is invalid")
    discovered = sorted(
        _frontmatter(path.read_bytes(), path.relative_to(plugin).as_posix())["name"]
        for path in (plugin / "skills").glob("*/SKILL.md")
    )
    if discovered != skill_names:
        raise CursorGenerationError("generated Cursor Skill inventory is incomplete")
    if (plugin / "AGENTS.md").exists() or (plugin / "hooks").exists():
        raise CursorGenerationError("generated package contains an unproved instruction or hook")


def _replace_generated(root: Path, stage: Path, project_id: str) -> None:
    targets = (
        Path(".cursor-plugin/marketplace.json"),
        Path("plugins") / project_id,
    )
    with tempfile.TemporaryDirectory(prefix=".cursor-backup-", dir=root) as tmp:
        backup = Path(tmp)
        moved: list[Path] = []
        installed: list[Path] = []
        try:
            for relative in targets:
                destination = root / relative
                if destination.exists():
                    backup_path = backup / relative
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, backup_path)
                    moved.append(relative)
            for relative in targets:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage / relative, destination)
                installed.append(relative)
        except OSError:
            for relative in reversed(installed):
                destination = root / relative
                if destination.is_dir():
                    shutil.rmtree(destination)
                elif destination.exists():
                    destination.unlink()
            for relative in moved:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup / relative, destination)
            raise


def generate(
    marketplace_root: Path,
    project_id: str,
    supplied_source: Path | None,
) -> dict:
    catalog = json.loads((marketplace_root / "catalog.json").read_text(encoding="utf-8"))
    entry = _catalog_entry(catalog, project_id)
    release = entry["release"]
    with _release_source(entry["github"], supplied_source) as source:
        try:
            record, commit, digest = _load_candidate(source, project_id, release)
        except IngestionError as error:
            raise CursorGenerationError(str(error)) from error
        if commit != entry["sha"]:
            raise CursorGenerationError(
                f"accepted commit {entry['sha']} disagrees with released commit {commit}"
            )
        if digest != entry["projectRecord"]["sha256"]:
            raise CursorGenerationError(
                "accepted Project Record digest disagrees with released bytes"
            )
        version_path = record["factSources"]["version"]
        version = _read_tree_bytes(source, commit, version_path).decode("utf-8").strip()
        manifest, field_sources = _cursor_manifest(
            source,
            commit,
            project_id,
            record,
            version,
        )
        source_files, skill_names = _source_files(
            source,
            commit,
            project_id,
            record,
        )

        repository = manifest.get("repository", f"https://github.com/{entry['github']}")
        if not isinstance(repository, str):
            raise CursorGenerationError("generated repository must be a string")
        marketplace_manifest = {
            "name": catalog["name"],
            "owner": catalog["owner"],
            "metadata": {"description": catalog["description"]},
            "plugins": [
                {
                    "name": project_id,
                    "source": f"./plugins/{project_id}",
                    "description": record["outcome"].strip(),
                    "version": version,
                }
            ],
        }
        provenance = {
            "schema": 1,
            "project": project_id,
            "release": release,
            "commit": commit,
            "projectRecord": {
                "path": RECORD_PATH,
                "sha256": digest,
            },
            "manifestFieldSources": field_sources,
            "files": [
                {
                    "path": path,
                    "source": item.source,
                    "sha256": hashlib.sha256(item.content).hexdigest(),
                    "mode": format(item.mode, "06o"),
                }
                for path, item in sorted(source_files.items())
            ],
        }

        marketplace_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".cursor-stage-", dir=marketplace_root) as tmp:
            stage = Path(tmp)
            plugin_root = stage / "plugins" / project_id
            for relative_path, source_file in source_files.items():
                _write_file(
                    plugin_root / relative_path,
                    source_file.content,
                    source_file.mode,
                )
            _write_file(
                plugin_root / ".cursor-plugin" / "plugin.json",
                _json_bytes(manifest),
            )
            _write_file(plugin_root / "SOURCE.json", _json_bytes(provenance))
            _write_file(
                plugin_root / "README.md",
                _readme(manifest["displayName"], release, commit, repository),
            )
            _write_file(
                stage / ".cursor-plugin" / "marketplace.json",
                _json_bytes(marketplace_manifest),
            )
            _validate_staged(stage, project_id, skill_names)
            _replace_generated(marketplace_root, stage, project_id)

    return {
        "project": project_id,
        "release": release,
        "commit": commit,
        "recordSha256": digest,
        "skills": skill_names,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="Accepted Project id from catalog.json")
    parser.add_argument(
        "--source",
        type=Path,
        help="Local Git source for deterministic generation; defaults to accepted GitHub",
    )
    parser.add_argument(
        "--marketplace-root",
        type=Path,
        default=ROOT,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    try:
        result = generate(
            args.marketplace_root.resolve(),
            args.project,
            args.source,
        )
    except (
        CursorGenerationError,
        IngestionError,
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as error:
        print(f"Cursor generation rejected: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
