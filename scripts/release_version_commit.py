#!/usr/bin/env python3
"""Tag and release a version commit on main that Toolybara did not release itself."""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from toolybara_promotion import MARKETPLACE_REPOSITORY, PromotionError, _gh_request, _version

REPO = f"/repos/{MARKETPLACE_REPOSITORY}"
TAGGER = {
    "name": "github-actions[bot]",
    "email": "41898282+github-actions[bot]@users.noreply.github.com",
}
WAKE_EVENT = "module_release_published"


def _release_check(root: Path) -> None:
    versionctl = root / "cursor/agentsmd/tools/versionctl/bin/versionctl"
    subprocess.run([str(versionctl), "release-check"], cwd=root, check=True)


def changelog_entry(root: Path, version: str) -> str:
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = f"## [{version}]"
    if heading not in changelog:
        raise PromotionError(f"CHANGELOG.md has no {heading} entry")
    return changelog[changelog.index(heading):].split("\n## [", 1)[0].strip()


def release_version_commit(
    root: Path,
    sha: str,
    *,
    request: Callable[..., dict | list | None] = _gh_request,
    release_check: Callable[[Path], None] = _release_check,
) -> dict:
    """Skip when the tag exists; otherwise check, tag, release, and wake reconciliation."""
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    tag = f"v{version}"
    _version(tag)
    reference = request("GET", f"{REPO}/git/ref/tags/{tag}", allow_not_found=True)
    if reference is not None:
        target = reference.get("object", {}) if isinstance(reference, dict) else {}
        if target.get("type") == "tag":
            target = (request("GET", f"{REPO}/git/tags/{target.get('sha')}") or {}).get("object", {})
        if target.get("sha") != sha:
            raise PromotionError(f"{tag} already exists but does not point to {sha}")
        return {"state": "skipped", "tag": tag, "reason": "tag already exists"}

    release_check(root)
    commit = request("GET", f"{REPO}/commits/{sha}")
    date = commit.get("commit", {}).get("committer", {}).get("date") if isinstance(commit, dict) else None
    if not isinstance(date, str):
        date = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    tag_object = request(
        "POST",
        f"{REPO}/git/tags",
        {
            "tag": tag,
            "message": f"ToolboxMD Marketplace {tag}",
            "object": sha,
            "type": "commit",
            "tagger": {**TAGGER, "date": date},
        },
    )
    tag_sha = tag_object.get("sha") if isinstance(tag_object, dict) else None
    if not isinstance(tag_sha, str):
        raise PromotionError("annotated tag object creation failed")
    request("POST", f"{REPO}/git/refs", {"ref": f"refs/tags/{tag}", "sha": tag_sha})
    release = request(
        "POST",
        f"{REPO}/releases",
        {
            "tag_name": tag,
            "target_commitish": sha,
            "name": f"ToolboxMD Marketplace {tag}",
            "body": changelog_entry(root, version),
            "draft": False,
            "prerelease": False,
        },
    )
    if not isinstance(release, dict) or release.get("tag_name") != tag or release.get("draft") is not False:
        raise PromotionError("Marketplace GitHub Release identity is invalid")
    request("POST", f"{REPO}/dispatches", {"event_type": WAKE_EVENT})
    return {"state": "released", "tag": tag, "releaseUrl": release.get("html_url"), "wake": WAKE_EVENT}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        result = release_version_commit(args.root.resolve(), args.sha)
    except (PromotionError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Version commit release failed: {error}", file=sys.stderr)
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
