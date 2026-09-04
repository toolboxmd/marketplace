#!/usr/bin/env python3
"""Reconcile released AgentsMD versions through Toolybara's trusted PR path."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import namedtuple
from collections.abc import Callable
from pathlib import Path


VERSION_TAG_RE = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
ReconciliationDecision = namedtuple(
    "ReconciliationDecision", "state candidate rejected wake_tag"
)
GENERATED_FILES = {
    ".agents/plugins/marketplace.json",
    ".claude-plugin/marketplace.json",
    ".cursor-plugin/marketplace.json",
    ".grok-plugin/marketplace.json",
    "CHANGELOG.md",
    "VERSION",
    "catalog.json",
}
GENERATED_PREFIXES = ("plugins/agentsmd/",)
EXPECTED_ACTOR = "toolybara[bot]"
EXPECTED_BRANCH = "toolybara/promote-agentsmd"
MARKETPLACE_REPOSITORY = "toolboxmd/marketplace"
SOURCE_REPOSITORY = "toolboxmd/agentsmd"


class PromotionError(RuntimeError):
    """A release cannot safely pass the Toolybara promotion contract."""


def validate_generated_paths(paths: set[str]) -> None:
    """Reject every change not produced by AgentsMD promotion and versioning."""

    unexpected = sorted(
        path
        for path in paths
        if path not in GENERATED_FILES
        and not any(path.startswith(prefix) for prefix in GENERATED_PREFIXES)
    )
    if unexpected:
        raise PromotionError(f"changes outside generated allowlist: {unexpected}")


def _run(*command: str, cwd: Path) -> str:
    result = subprocess.run(
        [*command],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PromotionError(f"{' '.join(command)} failed: {detail}")
    return result.stdout.strip()


def working_tree_id(root: Path) -> str:
    """Hash the complete non-ignored working tree without mutating its index."""

    paths = _run(
        "git",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        cwd=root,
    ).split("\0")
    digest = hashlib.sha256()
    for relative in sorted(path for path in paths if path):
        file_path = root / relative
        if not file_path.is_file():
            continue
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(file_path.stat().st_mode & 0o777).encode("ascii") + b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _catalog_by_name(root: Path) -> dict[str, dict]:
    document = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    entries = document.get("plugins")
    if not isinstance(entries, list):
        raise PromotionError("catalog plugins must be an array")
    by_name = {entry.get("name"): entry for entry in entries if isinstance(entry, dict)}
    if len(by_name) != len(entries) or "agentsmd" not in by_name:
        raise PromotionError("catalog Project identities must be unique and include agentsmd")
    return by_name


def validate_candidate_state(
    base_root: Path,
    candidate_root: Path,
    source: dict,
) -> str:
    """Validate promotion identity, preserved records, and one patch transition."""

    base_catalog = _catalog_by_name(base_root)
    candidate_catalog = _catalog_by_name(candidate_root)
    base_other = {name: entry for name, entry in base_catalog.items() if name != "agentsmd"}
    candidate_other = {
        name: entry for name, entry in candidate_catalog.items() if name != "agentsmd"
    }
    if candidate_other != base_other:
        raise PromotionError("non-AgentsMD catalog records changed")
    agentsmd = candidate_catalog["agentsmd"]
    expected_record = {
        "path": ".toolboxmd/project.json",
        "sha256": source["recordSha256"],
    }
    if (
        agentsmd.get("release") != source["release"]
        or agentsmd.get("sha") != source["commit"]
        or agentsmd.get("projectRecord") != expected_record
    ):
        raise PromotionError("candidate identity disagrees with the peeled source release")

    base_version = _version("v" + (base_root / "VERSION").read_text(encoding="utf-8").strip())
    candidate_text = (candidate_root / "VERSION").read_text(encoding="utf-8").strip()
    candidate_version = _version("v" + candidate_text)
    if candidate_version != (base_version[0], base_version[1], base_version[2] + 1):
        raise PromotionError("promotion must contain exactly one patch SemVer transition")
    changelog = (candidate_root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## \[{re.escape(candidate_text)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE):
        raise PromotionError("promotion changelog does not record the candidate version")
    return candidate_text


def _changed_paths(root: Path) -> set[str]:
    tracked = set(_run("git", "diff", "--name-only", "HEAD", cwd=root).splitlines())
    untracked = set(
        _run(
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            cwd=root,
        ).splitlines()
    )
    return {path for path in tracked | untracked if path}


def build_generated_candidate(
    *,
    base_root: Path,
    candidate_root: Path,
    source_root: Path,
    release: str,
) -> dict:
    """Generate one promotion inside an ephemeral candidate checkout."""

    ingest_output = _run(
        sys.executable,
        str(base_root / "scripts" / "ingest_project.py"),
        "agentsmd",
        release,
        "--source",
        str(source_root),
        "--marketplace-root",
        str(candidate_root),
        cwd=base_root,
    )
    source = json.loads(ingest_output)
    cursor_output = _run(
        sys.executable,
        str(base_root / "scripts" / "render_cursor.py"),
        "agentsmd",
        "--source",
        str(source_root),
        "--marketplace-root",
        str(candidate_root),
        cwd=base_root,
    )
    cursor = json.loads(cursor_output)
    for field in ("project", "release", "commit", "recordSha256"):
        if cursor.get(field) != source.get(field):
            raise PromotionError(f"Cursor generation disagrees on {field}")
    versionctl = base_root / "plugins" / "agentsmd" / "tools" / "versionctl" / "bin" / "versionctl"
    _run(
        str(versionctl),
        "prepare",
        "patch",
        "--reason",
        f"Promote AgentsMD {release} through Toolybara",
        cwd=candidate_root,
    )
    paths = _changed_paths(candidate_root)
    validate_generated_paths(paths)
    marketplace_version = validate_candidate_state(base_root, candidate_root, source)
    return {
        **source,
        "marketplaceVersion": marketplace_version,
        "changedPaths": sorted(paths),
        "tree": working_tree_id(candidate_root),
    }


def validate_pull_request(
    snapshot: dict,
    expected: dict,
    *,
    require_mergeable: bool,
    allow_merged: bool = False,
) -> None:
    """Bind a live Toolybara pull request to its exact validated identity."""

    head = snapshot.get("head", {})
    base = snapshot.get("base", {})
    actual = {
        "number": snapshot.get("number"),
        "state": snapshot.get("state"),
        "draft": snapshot.get("draft"),
        "actor": snapshot.get("user", {}).get("login"),
        "headRef": head.get("ref"),
        "headSha": head.get("sha"),
        "headRepository": head.get("repo", {}).get("full_name"),
        "baseRef": base.get("ref"),
        "baseSha": base.get("sha"),
    }
    merged_mode = allow_merged and snapshot.get("state") == "closed"
    if merged_mode:
        # GitHub may report the moved live base ref after a completed merge.
        actual["baseSha"] = expected["base"]
    required = {
        "number": expected["number"],
        "state": "closed" if merged_mode else "open",
        "draft": False,
        "actor": EXPECTED_ACTOR,
        "headRef": EXPECTED_BRANCH,
        "headSha": expected["head"],
        "headRepository": MARKETPLACE_REPOSITORY,
        "baseRef": "main",
        "baseSha": expected["base"],
    }
    if actual != required:
        raise PromotionError(f"live pull request identity changed: {actual}")
    if merged_mode:
        merge_sha = snapshot.get("merge_commit_sha")
        if snapshot.get("merged") is not True or not isinstance(merge_sha, str):
            raise PromotionError("closed pull request is not the exact merged candidate")
        if snapshot.get("merged_by", {}).get("login") != EXPECTED_ACTOR:
            raise PromotionError("merged pull request was not finalized by Toolybara")
    elif require_mergeable and snapshot.get("mergeable") is not True:
        raise PromotionError("live pull request is not mergeable")


def validate_previous_promotion(snapshot: dict, expected_head: str) -> None:
    """Authorize reuse of the retained branch after its prior exact merge."""

    actual = {
        "state": snapshot.get("state"),
        "merged": snapshot.get("merged"),
        "mergedBy": snapshot.get("merged_by", {}).get("login"),
        "actor": snapshot.get("user", {}).get("login"),
        "headRef": snapshot.get("head", {}).get("ref"),
        "headSha": snapshot.get("head", {}).get("sha"),
        "headRepository": snapshot.get("head", {}).get("repo", {}).get("full_name"),
        "baseRef": snapshot.get("base", {}).get("ref"),
    }
    expected = {
        "state": "closed",
        "merged": True,
        "mergedBy": EXPECTED_ACTOR,
        "actor": EXPECTED_ACTOR,
        "headRef": EXPECTED_BRANCH,
        "headSha": expected_head,
        "headRepository": MARKETPLACE_REPOSITORY,
        "baseRef": "main",
    }
    if actual != expected:
        raise PromotionError(f"retained promotion branch lacks a trusted merged owner: {actual}")


def merge_exact_head(
    number: int,
    head: str,
    *,
    request: Callable[[str, str, dict], dict],
) -> str:
    """Call GitHub's pull-request merge API with the validated exact head."""

    response = request(
        "PUT",
        f"/repos/{MARKETPLACE_REPOSITORY}/pulls/{number}/merge",
        {"merge_method": "squash", "sha": head},
    )
    merge_sha = response.get("sha")
    if response.get("merged") is not True or not isinstance(merge_sha, str):
        raise PromotionError(f"merge rejected: {response.get('message', response)}")
    return merge_sha


def _version(tag: str) -> tuple[int, int, int]:
    match = VERSION_TAG_RE.fullmatch(tag)
    if not match:
        raise PromotionError(f"release tag is not stable SemVer: {tag!r}")
    return tuple(int(part) for part in match.groups())


def select_candidate(
    releases: list[dict],
    *,
    current_tag: str,
    wake_tag: str | None,
    inspect: Callable[[str], dict],
) -> ReconciliationDecision:
    """Select the newest published stable release newer than accepted state."""

    current = _version(current_tag)
    published = {
        item.get("tag_name")
        for item in releases
        if not item.get("draft") and not item.get("prerelease")
    }
    stable = sorted(
        (tag for tag in published if isinstance(tag, str) and VERSION_TAG_RE.fullmatch(tag)),
        key=_version,
        reverse=True,
    )
    rejected: list[dict[str, str]] = []
    for tag in stable:
        if _version(tag) <= current:
            continue
        try:
            candidate = inspect(tag)
        except (PromotionError, OSError, ValueError) as error:
            rejected.append({"release": tag, "reason": str(error)})
            continue
        return ReconciliationDecision("candidate", candidate, rejected, wake_tag)
    state = "invalid" if rejected else "duplicate"
    return ReconciliationDecision(state, None, rejected, wake_tag)


def require_published_release(releases: list[dict], release: str) -> None:
    """Fail closed when the accepted release is no longer published stable."""

    if not any(
        item.get("tag_name") == release
        and not item.get("draft")
        and not item.get("prerelease")
        for item in releases
    ):
        raise PromotionError(
            f"accepted AgentsMD release is not published stable: {release}"
        )


def require_same_candidate(
    decision: ReconciliationDecision, expected_release: str
) -> dict:
    """Fail closed when reconciliation discovers a competing newer release."""

    actual = decision.candidate and decision.candidate.get("release")
    if decision.state != "candidate" or actual != expected_release:
        raise PromotionError(
            f"newest eligible release changed: expected {expected_release}, got {actual}"
        )
    return decision.candidate


def _gh_request(
    method: str,
    endpoint: str,
    payload: dict | None = None,
    *,
    allow_not_found: bool = False,
    token: str | None = None,
) -> dict | list | None:
    command = ["gh", "api", "--method", method, endpoint]
    encoded = None
    if payload is not None:
        command.extend(("--input", "-"))
        encoded = json.dumps(payload)
    result = subprocess.run(
        command,
        input=encoded,
        capture_output=True,
        text=True,
        env={**os.environ, **({"GH_TOKEN": token} if token else {})},
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        if allow_not_found and ("HTTP 404" in detail or "Not Found" in detail):
            return None
        raise PromotionError(f"GitHub API {method} {endpoint} failed: {detail}")
    if not result.stdout.strip():
        return {}
    value = json.loads(result.stdout)
    if not isinstance(value, (dict, list)):
        raise PromotionError(f"GitHub API {endpoint} returned unexpected JSON")
    return value


def _inspect_release(control_root: Path, source_root: Path, release: str) -> dict:
    module_path = control_root / "scripts" / "ingest_project.py"
    spec = importlib.util.spec_from_file_location("toolybara_ingest", module_path)
    if spec is None or spec.loader is None:
        raise PromotionError("cannot load the trusted Project Record validator")
    module = importlib.util.module_from_spec(spec)
    scripts = str(control_root / "scripts")
    inserted = scripts not in sys.path
    if inserted:
        sys.path.insert(0, scripts)
    try:
        spec.loader.exec_module(module)
        record, commit, digest = module._load_candidate(source_root, "agentsmd", release)
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise PromotionError(str(error)) from error
    finally:
        if inserted:
            sys.path.remove(scripts)
    return {
        "project": "agentsmd",
        "release": release,
        "commit": commit,
        "recordSha256": digest,
        "record": record,
    }


def _clone(url: str, destination: Path, *, token: str | None = None) -> None:
    environment = None
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        environment = {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        }
    result = subprocess.run(
        ["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", url, str(destination)],
        capture_output=True,
        text=True,
        env={**os.environ, **(environment or {})},
    )
    if result.returncode:
        raise PromotionError(result.stderr.strip() or f"git clone failed: {url}")


def _push(root: Path, branch: str, *, previous: str | None) -> None:
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise PromotionError("GH_TOKEN is required for Toolybara branch updates")
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    environment = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
    }
    command = ["git", "push", "origin", f"HEAD:refs/heads/{branch}"]
    if previous:
        command.append(f"--force-with-lease=refs/heads/{branch}:{previous}")
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, env=environment)
    if result.returncode:
        raise PromotionError(result.stderr.strip() or "Toolybara branch push failed")


def prepare_existing_branch(
    root: Path,
    *,
    previous: str,
    candidate_head: str,
    candidate_tree: str,
    base_sha: str,
    open_pull_requests: list[dict],
    closed_pull_requests: list[dict],
    request: Callable[..., dict | list | None] = _gh_request,
    push: Callable[..., None] = _push,
) -> str:
    """Bind or recover the retained promotion branch without trusting its owner."""

    if len(open_pull_requests) > 1:
        raise PromotionError("expected promotion branch has competing open pull requests")
    matching_closed: list[dict] = []
    if open_pull_requests:
        validate_pull_request(
            open_pull_requests[0],
            {
                "number": open_pull_requests[0]["number"],
                "head": previous,
                "base": base_sha,
            },
            require_mergeable=False,
        )
    else:
        matching_closed = [
            pull_request
            for pull_request in closed_pull_requests
            if pull_request.get("head", {}).get("sha") == previous
        ]
    if not open_pull_requests and matching_closed:
        prior = request(
            "GET",
            f"/repos/{MARKETPLACE_REPOSITORY}/pulls/{matching_closed[0]['number']}",
        )
        if not isinstance(prior, dict):
            raise PromotionError("prior promotion pull request was not found")
        validate_previous_promotion(prior, previous)
    elif not open_pull_requests:
        # A prior run may have pushed successfully and failed before PR creation.
        # Rewrite only the reserved branch with an exact lease and the current
        # Toolybara token, then let the caller create and validate the PR.
        push(root, EXPECTED_BRANCH, previous=previous)
        return candidate_head

    remote_commit = request(
        "GET", f"/repos/{MARKETPLACE_REPOSITORY}/git/commits/{previous}"
    )
    remote_tree = (
        remote_commit.get("tree", {}).get("sha")
        if isinstance(remote_commit, dict)
        else None
    )
    if remote_tree == candidate_tree:
        return previous
    push(root, EXPECTED_BRANCH, previous=previous)
    return candidate_head


def _current_release(root: Path) -> str:
    release = _catalog_by_name(root)["agentsmd"].get("release")
    if not isinstance(release, str):
        raise PromotionError("accepted AgentsMD catalog record has no release")
    _version(release)
    return release


def accepted_duplicate_evidence(
    root: Path,
    source: dict,
    *,
    base_sha: str,
) -> dict[str, str]:
    """Bind a duplicate result to its revalidated immutable source identity."""

    catalog = _catalog_by_name(root)["agentsmd"]
    catalog_record = catalog.get("projectRecord")
    provenance = json.loads(
        (root / "plugins" / "agentsmd" / "SOURCE.json").read_text(
            encoding="utf-8"
        )
    )
    provenance_record = provenance.get("projectRecord")
    if (
        not isinstance(catalog_record, dict)
        or catalog_record.get("path") != ".toolboxmd/project.json"
        or not isinstance(provenance_record, dict)
        or provenance_record.get("path") != ".toolboxmd/project.json"
    ):
        raise PromotionError("accepted AgentsMD Project Record path is invalid")

    inspected = {
        "release": source.get("release"),
        "commit": source.get("commit"),
        "recordSha256": source.get("recordSha256"),
    }
    catalog_identity = {
        "release": catalog.get("release"),
        "commit": catalog.get("sha"),
        "recordSha256": catalog_record.get("sha256"),
    }
    provenance_identity = {
        "release": provenance.get("release"),
        "commit": provenance.get("commit"),
        "recordSha256": provenance_record.get("sha256"),
    }
    if inspected != catalog_identity or inspected != provenance_identity:
        raise PromotionError(
            "accepted AgentsMD identity disagrees with the immutable source release"
        )

    return {
        "state": "duplicate",
        "base_sha": base_sha,
        "release": inspected["release"],
        "source_sha": inspected["commit"],
        "record_sha256": inspected["recordSha256"],
    }


def _published_releases() -> list[dict]:
    releases: list[dict] = []
    page = 1
    while True:
        value = _gh_request(
            "GET",
            f"/repos/{SOURCE_REPOSITORY}/releases?per_page=100&page={page}",
            token=os.environ.get("READ_TOKEN"),
        )
        if not isinstance(value, list):
            raise PromotionError("AgentsMD releases endpoint did not return an array")
        releases.extend(value)
        if len(value) < 100:
            return releases
        page += 1


def _main_sha() -> str:
    value = _gh_request(
        "GET",
        f"/repos/{MARKETPLACE_REPOSITORY}/git/ref/heads/main",
        token=os.environ.get("READ_TOKEN"),
    )
    sha = value.get("object", {}).get("sha") if isinstance(value, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise PromotionError("Marketplace main did not resolve to a full commit")
    return sha


def _write_outputs(path: Path | None, values: dict[str, object]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _append_summary(path: Path | None, lines: list[str]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _promotion_body(source: dict, marketplace_version: str) -> str:
    return "\n".join(
        (
            f"## Outcome\n\nPromote the newest eligible AgentsMD release, {source['release']}, through Toolybara.",
            "\n## Exact identity",
            f"\n- AgentsMD release: `{source['release']}`",
            f"- Peeled source commit: `{source['commit']}`",
            f"- Project Record SHA-256: `{source['recordSha256']}`",
            f"- Marketplace version: `{marketplace_version}`",
            "\n## Generation boundary",
            "\nThis pull request was authored by Toolybara from the trusted Marketplace control plane. Only the generated promotion allowlist and one patch SemVer transition may differ from main. Deterministic validation, not model review, owns this generated diff.",
            "\nCloses #17",
        )
    )


def _expected_pull_requests(state: str) -> list[dict]:
    head = EXPECTED_BRANCH.replace("/", "%2F")
    value = _gh_request(
        "GET",
        f"/repos/{MARKETPLACE_REPOSITORY}/pulls?state={state}&base=main&head=toolboxmd:{head}&sort=updated&direction=desc",
    )
    if not isinstance(value, list):
        raise PromotionError("pull request query did not return an array")
    return value


def reconcile(args: argparse.Namespace) -> dict:
    root = Path(__file__).resolve().parents[1]
    base_sha = _main_sha()
    if _run("git", "rev-parse", "HEAD", cwd=root) != base_sha:
        raise PromotionError("trusted workflow checkout is not the live main commit")

    with tempfile.TemporaryDirectory(prefix="toolybara-reconcile-") as tmp:
        temp = Path(tmp)
        source_root = temp / "agentsmd"
        candidate_root = temp / "marketplace"
        _clone(f"https://github.com/{SOURCE_REPOSITORY}.git", source_root)
        current_release = _current_release(root)
        published_releases = _published_releases()
        decision = select_candidate(
            published_releases,
            current_tag=current_release,
            wake_tag=args.wake_tag or None,
            inspect=lambda tag: _inspect_release(root, source_root, tag),
        )
        if decision.state == "invalid":
            _append_summary(
                args.summary,
                ["### Toolybara reconciliation", "", "- State: invalid", f"- Rejections: `{json.dumps(decision.rejected, sort_keys=True)}`"],
            )
            raise PromotionError(f"no valid unreconciled release: {decision.rejected}")
        if decision.state == "duplicate":
            require_published_release(published_releases, current_release)
            values = accepted_duplicate_evidence(
                root,
                _inspect_release(root, source_root, current_release),
                base_sha=base_sha,
            )
            _write_outputs(args.output, values)
            _append_summary(
                args.summary,
                [
                    "### Toolybara reconciliation",
                    "",
                    "- State: duplicate/no-op",
                    f"- Accepted AgentsMD release: `{values['release']}`",
                    f"- Peeled source commit: `{values['source_sha']}`",
                    f"- Project Record SHA-256: `{values['record_sha256']}`",
                    f"- Wake hint: `{args.wake_tag or 'none'}`",
                ],
            )
            return values

        source = decision.candidate
        token = os.environ.get("GH_TOKEN")
        if not token:
            raise PromotionError("GH_TOKEN is required for Toolybara reconciliation")
        _clone(f"https://github.com/{MARKETPLACE_REPOSITORY}.git", candidate_root, token=token)
        _run("git", "checkout", "--detach", base_sha, cwd=candidate_root)
        first = build_generated_candidate(
            base_root=root,
            candidate_root=candidate_root,
            source_root=source_root,
            release=source["release"],
        )
        second = build_generated_candidate(
            base_root=root,
            candidate_root=candidate_root,
            source_root=source_root,
            release=source["release"],
        )
        if first != second:
            raise PromotionError("second generation run was not idempotent")
        _run("bash", "tests/run-all.sh", cwd=candidate_root)
        _run("git", "config", "user.name", "Toolybara", cwd=candidate_root)
        _run(
            "git",
            "config",
            "user.email",
            "toolybara@users.noreply.github.com",
            cwd=candidate_root,
        )
        _run("git", "add", "--all", cwd=candidate_root)
        _run(
            "git",
            "commit",
            "-m",
            f"chore: promote AgentsMD {source['release']}",
            cwd=candidate_root,
        )
        candidate_head = _run("git", "rev-parse", "HEAD", cwd=candidate_root)
        candidate_tree = _run("git", "rev-parse", "HEAD^{tree}", cwd=candidate_root)
        _run(
            str(root / "plugins" / "agentsmd" / "tools" / "versionctl" / "bin" / "versionctl"),
            "release-check",
            cwd=candidate_root,
        )

        branch_ref = _gh_request(
            "GET",
            f"/repos/{MARKETPLACE_REPOSITORY}/git/ref/heads/{EXPECTED_BRANCH.replace('/', '%2F')}",
            allow_not_found=True,
        )
        previous = branch_ref.get("object", {}).get("sha") if isinstance(branch_ref, dict) else None
        pull_requests = _expected_pull_requests("open")
        if previous:
            candidate_head = prepare_existing_branch(
                candidate_root,
                previous=previous,
                candidate_head=candidate_head,
                candidate_tree=candidate_tree,
                base_sha=base_sha,
                open_pull_requests=pull_requests,
                closed_pull_requests=(
                    [] if pull_requests else _expected_pull_requests("closed")
                ),
            )
        else:
            if pull_requests:
                raise PromotionError("expected pull request exists without its promotion branch")
            _push(candidate_root, EXPECTED_BRANCH, previous=None)

        body = _promotion_body(source, first["marketplaceVersion"])
        if pull_requests:
            pull_request = _gh_request(
                "PATCH",
                f"/repos/{MARKETPLACE_REPOSITORY}/pulls/{pull_requests[0]['number']}",
                {"title": f"Promote AgentsMD {source['release']} through Toolybara", "body": body},
            )
        else:
            pull_request = _gh_request(
                "POST",
                f"/repos/{MARKETPLACE_REPOSITORY}/pulls",
                {
                    "title": f"Promote AgentsMD {source['release']} through Toolybara",
                    "head": EXPECTED_BRANCH,
                    "base": "main",
                    "body": body,
                    "maintainer_can_modify": False,
                },
            )
        if not isinstance(pull_request, dict):
            raise PromotionError("pull request mutation returned no document")
        number = pull_request.get("number")
        live_head = pull_request.get("head", {}).get("sha")
        if live_head != candidate_head:
            raise PromotionError("created pull request does not expose the pushed exact head")
        validate_pull_request(
            pull_request,
            {"number": number, "head": candidate_head, "base": base_sha},
            require_mergeable=False,
        )
        values = {
            "state": "candidate",
            "pr_number": number,
            "base_sha": base_sha,
            "head_sha": candidate_head,
            "release": source["release"],
            "source_sha": source["commit"],
            "record_sha256": source["recordSha256"],
            "marketplace_version": first["marketplaceVersion"],
        }
        _write_outputs(args.output, values)
        _append_summary(
            args.summary,
            [
                "### Toolybara reconciliation",
                "",
                "- State: candidate",
                f"- Pull request: `#{number}`",
                f"- Exact head: `{candidate_head}`",
                f"- AgentsMD release: `{source['release']}`",
                f"- Peeled source commit: `{source['commit']}`",
                f"- Project Record SHA-256: `{source['recordSha256']}`",
                f"- Rejected newer candidates: `{json.dumps(decision.rejected, sort_keys=True)}`",
            ],
        )
        return values


def _regenerate_and_compare(
    base_root: Path,
    candidate_root: Path,
    source_root: Path,
    source: dict,
) -> None:
    with tempfile.TemporaryDirectory(prefix="toolybara-validate-") as tmp:
        regenerated = Path(tmp) / "marketplace"
        result = subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(base_root), str(regenerated)],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise PromotionError(result.stderr.strip() or "base clone failed")
        _run("git", "checkout", "--detach", _run("git", "rev-parse", "HEAD", cwd=base_root), cwd=regenerated)
        first = build_generated_candidate(
            base_root=base_root,
            candidate_root=regenerated,
            source_root=source_root,
            release=source["release"],
        )
        second = build_generated_candidate(
            base_root=base_root,
            candidate_root=regenerated,
            source_root=source_root,
            release=source["release"],
        )
        if first != second or working_tree_id(regenerated) != working_tree_id(candidate_root):
            raise PromotionError("candidate differs from deterministic regeneration")


def _validate_candidate_checkout(
    args: argparse.Namespace,
    *,
    require_newest: bool,
    release_check: bool = True,
) -> dict:
    base_root = args.base_root.resolve()
    candidate_root = args.candidate_root.resolve()
    if _run("git", "rev-parse", "HEAD", cwd=base_root) != args.base_sha:
        raise PromotionError("trusted base checkout is not the reconciled base")
    if _run("git", "rev-parse", "HEAD", cwd=candidate_root) != args.head_sha:
        raise PromotionError("candidate checkout is not the validated head")
    paths = set(
        _run(
            "git",
            "diff",
            "--name-only",
            f"{args.base_sha}..{args.head_sha}",
            cwd=candidate_root,
        ).splitlines()
    )
    validate_generated_paths(paths)

    with tempfile.TemporaryDirectory(prefix="toolybara-source-") as tmp:
        source_root = Path(tmp) / "agentsmd"
        _clone(f"https://github.com/{SOURCE_REPOSITORY}.git", source_root)
        if require_newest:
            decision = select_candidate(
                _published_releases(),
                current_tag=_current_release(base_root),
                wake_tag=None,
                inspect=lambda tag: _inspect_release(base_root, source_root, tag),
            )
            source = require_same_candidate(decision, args.release)
        else:
            source = _inspect_release(base_root, source_root, args.release)
        if source["commit"] != args.source_sha or source["recordSha256"] != args.record_sha256:
            raise PromotionError("source identity changed after reconciliation")
        version = validate_candidate_state(base_root, candidate_root, source)
        if version != args.marketplace_version:
            raise PromotionError("Marketplace version changed after reconciliation")
        _regenerate_and_compare(base_root, candidate_root, source_root, source)

    _run("bash", "tests/run-all.sh", cwd=candidate_root)
    if release_check:
        _run(
            str(
                base_root
                / "plugins"
                / "agentsmd"
                / "tools"
                / "versionctl"
                / "bin"
                / "versionctl"
            ),
            "release-check",
            cwd=candidate_root,
        )
    evidence = {
        "pr": args.pr_number,
        "base": args.base_sha,
        "head": args.head_sha,
        "release": args.release,
        "source": args.source_sha,
        "recordSha256": args.record_sha256,
        "marketplaceVersion": args.marketplace_version,
        "changedPaths": sorted(paths),
    }
    _append_summary(
        args.summary,
        ["### Exact Toolybara candidate validation", "", *(f"- {key}: `{value}`" for key, value in evidence.items())],
    )
    return evidence


def validate_live(args: argparse.Namespace) -> dict:
    snapshot = _gh_request("GET", f"/repos/{MARKETPLACE_REPOSITORY}/pulls/{args.pr_number}")
    if not isinstance(snapshot, dict):
        raise PromotionError("live pull request was not found")
    validate_pull_request(
        snapshot,
        {"number": args.pr_number, "head": args.head_sha, "base": args.base_sha},
        require_mergeable=args.require_mergeable,
    )
    if _main_sha() != args.base_sha:
        raise PromotionError("Marketplace main moved after reconciliation")
    return _validate_candidate_checkout(args, require_newest=True)


def ensure_release(
    version: str,
    merge_sha: str,
    candidate_root: Path,
    *,
    request: Callable[..., dict | list | None],
) -> dict:
    tag = f"v{version}"
    ref_endpoint = f"/repos/{MARKETPLACE_REPOSITORY}/git/ref/tags/{tag}"
    reference = request("GET", ref_endpoint, allow_not_found=True)
    if reference is None:
        commit = request("GET", f"/repos/{MARKETPLACE_REPOSITORY}/commits/{merge_sha}")
        tagger_date = commit.get("commit", {}).get("committer", {}).get("date") if isinstance(commit, dict) else None
        if not isinstance(tagger_date, str):
            tagger_date = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        tag_object = request(
            "POST",
            f"/repos/{MARKETPLACE_REPOSITORY}/git/tags",
            {
                "tag": tag,
                "message": f"ToolboxMD Marketplace {tag}",
                "object": merge_sha,
                "type": "commit",
                "tagger": {
                    "name": "Toolybara",
                    "email": "toolybara@users.noreply.github.com",
                    "date": tagger_date,
                },
            },
        )
        tag_object_sha = tag_object.get("sha") if isinstance(tag_object, dict) else None
        if not isinstance(tag_object_sha, str):
            raise PromotionError("annotated tag object creation failed")
        reference = request(
            "POST",
            f"/repos/{MARKETPLACE_REPOSITORY}/git/refs",
            {"ref": f"refs/tags/{tag}", "sha": tag_object_sha},
        )
    ref_sha = reference.get("object", {}).get("sha") if isinstance(reference, dict) else None
    if not isinstance(ref_sha, str):
        raise PromotionError("Marketplace release tag reference is invalid")
    tag_object = request("GET", f"/repos/{MARKETPLACE_REPOSITORY}/git/tags/{ref_sha}")
    target = tag_object.get("object", {}).get("sha") if isinstance(tag_object, dict) else None
    if target != merge_sha:
        raise PromotionError(f"{tag} does not point to the exact merge commit")

    release = request(
        "GET",
        f"/repos/{MARKETPLACE_REPOSITORY}/releases/tags/{tag}",
        allow_not_found=True,
    )
    if release is None:
        changelog = (candidate_root / "CHANGELOG.md").read_text(encoding="utf-8")
        heading = f"## [{version}]"
        start = changelog.index(heading)
        rest = changelog[start:]
        body = rest.split("\n## [", 1)[0].strip()
        release = request(
            "POST",
            f"/repos/{MARKETPLACE_REPOSITORY}/releases",
            {
                "tag_name": tag,
                "target_commitish": merge_sha,
                "name": f"ToolboxMD Marketplace {tag}",
                "body": body,
                "draft": False,
                "prerelease": False,
            },
        )
    if (
        not isinstance(release, dict)
        or release.get("tag_name") != tag
        or release.get("draft") is not False
        or release.get("prerelease") is not False
    ):
        raise PromotionError("Marketplace GitHub Release identity is invalid")
    return release


def validate_merged_result(
    args: argparse.Namespace,
    merged_commit: dict,
    candidate_commit: dict,
    *,
    validate_drift: Callable[[str], dict],
) -> dict | None:
    """Accept the exact tree or fully revalidate a squash merged on a moved base."""

    parents = merged_commit.get("parents")
    if not isinstance(parents, list) or len(parents) != 1:
        raise PromotionError("Marketplace squash merge does not have one exact parent")
    actual_base = parents[0].get("sha") if isinstance(parents[0], dict) else None
    if not isinstance(actual_base, str):
        raise PromotionError("Marketplace squash merge parent is invalid")
    merged_tree = merged_commit.get("tree", {}).get("sha")
    candidate_tree = candidate_commit.get("tree", {}).get("sha")
    if not isinstance(merged_tree, str) or not isinstance(candidate_tree, str):
        raise PromotionError("merged or candidate tree identity is invalid")
    if actual_base == args.base_sha:
        if merged_tree != candidate_tree:
            raise PromotionError("merged tree differs from the exact validated candidate")
        return None
    return validate_drift(actual_base)


def _validate_drifted_merge(
    args: argparse.Namespace,
    merge_sha: str,
    actual_base: str,
    *,
    require_newest: bool,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="toolybara-merged-") as tmp:
        root = Path(tmp)
        base_root = root / "base"
        merged_root = root / "merged"
        url = f"https://github.com/{MARKETPLACE_REPOSITORY}.git"
        _clone(url, base_root)
        _clone(url, merged_root)
        _run("git", "checkout", "--detach", actual_base, cwd=base_root)
        _run("git", "checkout", "--detach", merge_sha, cwd=merged_root)
        merged_args = argparse.Namespace(
            **{
                **vars(args),
                "base_root": base_root,
                "candidate_root": merged_root,
                "base_sha": actual_base,
                "head_sha": merge_sha,
            }
        )
        evidence = _validate_candidate_checkout(
            merged_args,
            require_newest=require_newest,
        )
        return {
            **evidence,
            "reconciledBase": args.base_sha,
            "validatedHead": args.head_sha,
            "actualMergeBase": actual_base,
        }


def _supersede_manual_pr(
    toolybara_pr: int,
    merge_sha: str,
    release_url: str,
    *,
    request: Callable[..., dict | list | None],
) -> None:
    manual = request("GET", f"/repos/{MARKETPLACE_REPOSITORY}/pulls/15")
    if not isinstance(manual, dict):
        raise PromotionError("manual pull request #15 was not found")
    if manual.get("merged") is not False:
        raise PromotionError("manual pull request #15 is not proven unmerged")
    if manual.get("state") not in {"open", "closed"}:
        raise PromotionError("manual pull request #15 has an invalid state")
    body = (
        f"Superseded by Toolybara-authored PR #{toolybara_pr}, merged as `{merge_sha}` "
        f"and published at {release_url}. PR #15 was a manual proposal and was not "
        "merged or automatic delivery."
    )
    comments = request(
        "GET", f"/repos/{MARKETPLACE_REPOSITORY}/issues/15/comments?per_page=100"
    )
    if not isinstance(comments, list):
        raise PromotionError("manual pull request #15 comments were not found")
    has_exact_comment = any(
        isinstance(comment, dict) and comment.get("body") == body
        for comment in comments
    )
    if manual.get("state") == "closed":
        if not has_exact_comment:
            raise PromotionError(
                "closed manual pull request #15 lacks exact supersession evidence"
            )
        return
    if not has_exact_comment:
        request(
            "POST",
            f"/repos/{MARKETPLACE_REPOSITORY}/issues/15/comments",
            {"body": body},
        )
    closed = request(
        "PATCH", f"/repos/{MARKETPLACE_REPOSITORY}/pulls/15", {"state": "closed"}
    )
    if (
        not isinstance(closed, dict)
        or closed.get("state") != "closed"
        or closed.get("merged") is not False
    ):
        raise PromotionError("manual pull request #15 did not close")
    verified = request("GET", f"/repos/{MARKETPLACE_REPOSITORY}/pulls/15")
    if (
        not isinstance(verified, dict)
        or verified.get("state") != "closed"
        or verified.get("merged") is not False
    ):
        raise PromotionError("manual pull request #15 is not closed and unmerged")


def finalize(args: argparse.Namespace) -> dict:
    snapshot = _gh_request("GET", f"/repos/{MARKETPLACE_REPOSITORY}/pulls/{args.pr_number}")
    if not isinstance(snapshot, dict):
        raise PromotionError("live pull request was not found")
    already_merged = snapshot.get("state") == "closed"
    if already_merged:
        validate_pull_request(
            snapshot,
            {"number": args.pr_number, "head": args.head_sha, "base": args.base_sha},
            require_mergeable=False,
            allow_merged=True,
        )
        evidence = _validate_candidate_checkout(
            args,
            require_newest=False,
            release_check=False,
        )
    else:
        evidence = validate_live(args)
        snapshot = _gh_request(
            "GET", f"/repos/{MARKETPLACE_REPOSITORY}/pulls/{args.pr_number}"
        )
        validate_pull_request(
            snapshot,
            {"number": args.pr_number, "head": args.head_sha, "base": args.base_sha},
            require_mergeable=True,
        )
        if _main_sha() != args.base_sha:
            raise PromotionError("Marketplace main moved immediately before merge")
    toolybara_token = os.environ.get("TOOLYBARA_TOKEN")
    if not toolybara_token:
        raise PromotionError("TOOLYBARA_TOKEN is required for finalization")

    def write_request(
        method: str,
        endpoint: str,
        payload: dict | None = None,
        *,
        allow_not_found: bool = False,
    ) -> dict | list | None:
        return _gh_request(
            method,
            endpoint,
            payload,
            allow_not_found=allow_not_found,
            token=toolybara_token,
        )

    if already_merged:
        merge_sha = snapshot["merge_commit_sha"]
    else:
        merge_sha = merge_exact_head(args.pr_number, args.head_sha, request=write_request)
        main_sha = _main_sha()
        if main_sha != merge_sha:
            raise PromotionError("Marketplace main does not equal the merge API result")
        snapshot = _gh_request(
            "GET", f"/repos/{MARKETPLACE_REPOSITORY}/pulls/{args.pr_number}"
        )
        if not isinstance(snapshot, dict):
            raise PromotionError("merged pull request was not found")
        validate_pull_request(
            snapshot,
            {"number": args.pr_number, "head": args.head_sha, "base": args.base_sha},
            require_mergeable=False,
            allow_merged=True,
        )
    merged_commit = _gh_request("GET", f"/repos/{MARKETPLACE_REPOSITORY}/git/commits/{merge_sha}")
    candidate_commit = _gh_request("GET", f"/repos/{MARKETPLACE_REPOSITORY}/git/commits/{args.head_sha}")
    if not isinstance(merged_commit, dict) or not isinstance(candidate_commit, dict):
        raise PromotionError("merged or candidate commit identity is missing")
    drift_evidence = validate_merged_result(
        args,
        merged_commit,
        candidate_commit,
        validate_drift=lambda actual_base: _validate_drifted_merge(
            args,
            merge_sha,
            actual_base,
            require_newest=not already_merged,
        ),
    )
    if drift_evidence is not None:
        evidence = drift_evidence
    release = ensure_release(
        args.marketplace_version,
        merge_sha,
        args.candidate_root.resolve(),
        request=write_request,
    )
    release_url = release.get("html_url")
    if not isinstance(release_url, str):
        raise PromotionError("Marketplace GitHub Release URL is missing")
    _supersede_manual_pr(args.pr_number, merge_sha, release_url, request=write_request)
    result = {**evidence, "merge": merge_sha, "releaseUrl": release_url}
    _append_summary(
        args.summary,
        [
            "### Toolybara finalization",
            "",
            f"- Rechecked exact head: `{args.head_sha}`",
            f"- Merge commit: `{merge_sha}`",
            f"- Marketplace tag: `v{args.marketplace_version}`",
            f"- GitHub Release: {release_url}",
            "- Manual PR #15: closed as a superseded manual proposal",
        ],
    )
    return result


def _common_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--record-sha256", required=True)
    parser.add_argument("--marketplace-version", required=True)
    parser.add_argument("--require-mergeable", action="store_true")
    parser.add_argument("--summary", type=Path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    reconcile_parser = commands.add_parser("reconcile")
    reconcile_parser.add_argument("--wake-tag", default="")
    reconcile_parser.add_argument("--output", type=Path)
    reconcile_parser.add_argument("--summary", type=Path)
    validate_parser = commands.add_parser("validate")
    _common_parser(validate_parser)
    finalize_parser = commands.add_parser("finalize")
    _common_parser(finalize_parser)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "reconcile":
            result = reconcile(args)
        elif args.command == "validate":
            result = validate_live(args)
        else:
            result = finalize(args)
    except (PromotionError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        _append_summary(
            getattr(args, "summary", None),
            ["### Toolybara promotion failed", "", f"- Error: `{error}`", "- Result: candidate pull request remains open; last released Marketplace state is unchanged unless the exact-head merge already succeeded"],
        )
        print(f"Toolybara promotion rejected: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
