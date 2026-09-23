"""Reviewed enrollment, separate from published catalog state and wake hints."""

import json
import re
from pathlib import Path, PurePosixPath

POLICY_PATH = "toolybara/modules.json"
PROJECT_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def project_id(value: str) -> str:
    if not isinstance(value, str) or not PROJECT_ID.fullmatch(value):
        raise ValueError(f"invalid promotion Project id: {value!r}")
    return value


def branch(project: str) -> str:
    return f"toolybara/promote-{project_id(project)}"


def modules(root: Path) -> dict[str, dict]:
    policy = json.loads((root / POLICY_PATH).read_text())
    if not isinstance(policy, dict) or set(policy) != {"schema", "modules"} or policy["schema"] != 1:
        raise ValueError("invalid Toolybara enrollment policy")
    entries = policy["modules"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("Toolybara enrollment must contain approved modules")
    result = {}
    repositories = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"id", "github", "category", "cursor", "cursorRuntime"}:
            raise ValueError("invalid Toolybara module enrollment")
        name = project_id(entry["id"])
        repository = entry["github"]
        if not isinstance(repository, str) or not re.fullmatch(r"toolboxmd/[a-z0-9][a-z0-9._-]*", repository):
            raise ValueError("enrolled source must name an exact ToolboxMD repository")
        if name in result or repository in repositories:
            raise ValueError("duplicate Toolybara enrollment")
        if not isinstance(entry["category"], str) or not entry["category"].strip():
            raise ValueError("enrolled module requires a category")
        if not isinstance(entry["cursor"], bool):
            raise ValueError("Cursor delivery must be explicitly enabled or disabled")
        paths = entry["cursorRuntime"]
        if (not isinstance(paths, list) or any(not isinstance(path, str) for path in paths)
                or len(set(paths)) != len(paths) or not entry["cursor"] and paths):
            raise ValueError("invalid Cursor runtime paths")
        for path in paths:
            if (not isinstance(path, str) or not path or "\\" in path
                    or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts
                    or path.startswith(".") or path in {"skills", "README.md", "SOURCE.json", "VERSION"}):
                raise ValueError("Cursor runtime path escapes its approved source")
        result[name] = entry
        repositories.add(repository)
    return result


def enrolled(root: Path, project: str) -> dict:
    entries = modules(root)
    if project not in entries:
        raise ValueError(f"Project is not enrolled for Toolybara promotion: {project!r}")
    return entries[project]
