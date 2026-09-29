#!/usr/bin/env python3
"""Tag and release a version commit on main that Toolybara did not release itself.

An existing tag counts as done only when it is annotated, points at the pushed
commit, and has one published release; a missing release is recovered.
"""

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


def _releases_for(tag: str, request: Callable[..., dict | list | None]) -> list[dict]:
    """Every release, including drafts, whose tag name is the version tag."""
    found, page = [], 1
    while True:
        releases = request("GET", f"{REPO}/releases?per_page=100&page={page}")
        if not isinstance(releases, list):
            raise PromotionError("Marketplace release list is invalid")
        found.extend(item for item in releases if isinstance(item, dict) and item.get("tag_name") == tag)
        if len(releases) < 100:
            return found
        page += 1


def _existing_release_state(tag: str, sha: str, reference, request: Callable[..., dict | list | None]) -> str:
    """Return complete or missing-release for a valid annotated tag; fail on anything else."""
    target = reference.get("object") if isinstance(reference, dict) else None
    if not isinstance(target, dict) or target.get("type") != "tag":
        raise PromotionError(f"{tag} exists but is not an annotated tag; fix it manually")
    annotation = request("GET", f"{REPO}/git/tags/{target.get('sha')}")
    pointed = annotation.get("object") if isinstance(annotation, dict) else None
    if not isinstance(pointed, dict) or annotation.get("tag") != tag or pointed.get("type") != "commit":
        raise PromotionError(f"{tag} annotation is invalid")
    if pointed.get("sha") != sha:
        raise PromotionError(f"{tag} already exists but does not point to {sha}")
    releases = _releases_for(tag, request)
    if not releases:
        return "missing-release"
    if len(releases) != 1:
        raise PromotionError(f"{tag} has {len(releases)} releases; fix it manually")
    release = releases[0]
    if release.get("draft") is not False:
        raise PromotionError(f"{tag} has only a draft release; publish or delete it manually")
    if release.get("prerelease") is not False or not release.get("published_at"):
        raise PromotionError(f"{tag} release is not a stable published release")
    return "complete"


def _wake_reconciliation(request: Callable[..., dict | list | None]) -> None:
    # Reconciliation treats repeats as duplicate, so resending on rerun is safe
    # and recovers a run whose release succeeded but whose dispatch failed.
    request("POST", f"{REPO}/dispatches", {"event_type": WAKE_EVENT})


def _publish_release(root: Path, sha: str, version: str, tag: str,
                     request: Callable[..., dict | list | None]) -> dict:
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
    _wake_reconciliation(request)
    return release


def release_version_commit(
    root: Path,
    sha: str,
    *,
    request: Callable[..., dict | list | None] = _gh_request,
    release_check: Callable[[Path], None] = _release_check,
) -> dict:
    """Resend the wake-up for a complete release, recover a missing one, or check, tag, release, and wake reconciliation."""
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    tag = f"v{version}"
    _version(tag)
    reference = request("GET", f"{REPO}/git/ref/tags/{tag}", allow_not_found=True)
    if reference is not None:
        if _existing_release_state(tag, sha, reference, request) == "complete":
            _wake_reconciliation(request)
            return {"state": "resent", "tag": tag, "wake": WAKE_EVENT,
                    "reason": "annotated tag and published release exist; resent reconciliation wake-up"}
        release = _publish_release(root, sha, version, tag, request)
        return {"state": "recovered", "tag": tag, "releaseUrl": release.get("html_url"), "wake": WAKE_EVENT}

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
    release = _publish_release(root, sha, version, tag, request)
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
