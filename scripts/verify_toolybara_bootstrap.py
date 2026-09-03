#!/usr/bin/env python3
"""Validate Toolybara bootstrap policy and evidence without reading secrets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "toolybara" / "bootstrap-policy.json"
WIZARD_PATH = ROOT / "scripts" / "bootstrap_toolybara.sh"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "toolybara-bootstrap-verification.yml"
STAGES = [
    "Preflight and settings baseline",
    "Register Toolybara",
    "Install on Marketplace only",
    "Store the public client ID",
    "Store the private key",
    "Verify Toolybara identity and scope",
    "Prove settings unchanged and clean up",
]
LIBRARY_SHA256 = "36ddf7aa3a7da152768664bddc48451a6a738f44840eb94e1c5cb014c531c02d"
ACTION_SHA = "bcd2ba49218906704ab6c1aa796996da409d3eb1"
REGISTRATION_URL = (
    "https://github.com/organizations/toolboxmd/settings/apps/new?name=Toolybara&"
    "description=The%20ToolboxMD%20release%20courier.%20Toolybara%20carries%20"
    "verified%20ToolboxMD%20releases%20into%20the%20Marketplace%20and%20merges%20"
    "them%20when%20every%20check%20is%20green.&url=https%3A%2F%2Fgithub.com%2F"
    "toolboxmd%2Fmarketplace&public=false&webhook_active=false&contents=write&"
    "pull_requests=write"
)


def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def policy_summary(policy: dict) -> dict:
    return {
        "actor": policy["app"]["actor"],
        "appInstallationRepositories": policy["installation"]["repositories"],
        "appPermissions": policy["app"]["repositoryPermissions"],
        "credentialRepositories": policy["actionsCredentials"]["secret"][
            "repositories"
        ],
        "repositorySettings": policy["repositorySettings"],
        "secret": policy["actionsCredentials"]["secret"]["name"],
        "variable": policy["actionsCredentials"]["variable"]["name"],
    }


def fail(message: str) -> None:
    raise SystemExit(message)


def verify_policy(policy: dict) -> None:
    expected = {
        "owner": "toolboxmd",
        "name": "Toolybara",
        "slug": "toolybara",
        "actor": "toolybara[bot]",
        "description": (
            "The ToolboxMD release courier. Toolybara carries verified ToolboxMD "
            "releases into the Marketplace and merges them when every check is green."
        ),
        "homepage": "https://github.com/toolboxmd/marketplace",
        "public": False,
        "webhookActive": False,
        "repositoryPermissions": {
            "metadata": "read",
            "contents": "write",
            "pull_requests": "write",
        },
        "organizationPermissions": {},
        "accountPermissions": {},
        "events": [],
    }
    if policy.get("schema") != 1 or policy.get("app") != expected:
        fail("Toolybara App policy drifted")
    if policy.get("installation") != {
        "owner": "toolboxmd",
        "repositorySelection": "selected",
        "repositories": ["marketplace"],
    }:
        fail("Toolybara installation scope drifted")
    expected_credential = {
        "scope": "organization",
        "visibility": "selected",
        "repositories": ["agentsmd", "marketplace"],
    }
    credentials = policy.get("actionsCredentials", {})
    for kind, name in (
        ("variable", "TOOLYBARA_CLIENT_ID"),
        ("secret", "TOOLYBARA_PRIVATE_KEY"),
    ):
        actual = credentials.get(kind, {})
        if actual != {"name": name, **expected_credential}:
            fail(f"Toolybara {kind} policy drifted")
    if policy.get("repositorySettings") != {
        "repository": "toolboxmd/marketplace",
        "defaultBranch": "main",
        "allowAutoMerge": False,
        "deleteBranchOnMerge": False,
        "branchProtection": False,
        "requiredStatusChecks": False,
        "blockedDirectPushes": False,
        "forcePushesBlocked": False,
        "bypassActors": [],
        "rulesets": [],
    }:
        fail("Marketplace unchanged-settings policy drifted")


def verify_static() -> dict:
    verify_policy(load_policy())
    wizard = WIZARD_PATH.read_text(encoding="utf-8")
    marker = "# STAGES: author this section."
    library = wizard[: wizard.index(marker)].encode()
    library_sha = hashlib.sha256(library).hexdigest()
    if library_sha != LIBRARY_SHA256:
        fail("wizard library differs from the canonical template")
    stages = re.findall(r'^stage "([^"]+)"$', wizard, flags=re.MULTILINE)
    if stages != STAGES or "TOTAL_STAGES=7" not in wizard:
        fail("wizard stage order drifted")
    subprocess.run(["bash", "-n", str(WIZARD_PATH)], check=True)

    normalized_wizard = re.sub(r"\s+", " ", wizard.replace("\\\n", ""))
    required_wizard_text = (
        REGISTRATION_URL,
        "https://github.com/organizations/toolboxmd/settings/installations",
        "https://github.com/apps/toolybara/installations/new",
        'gh variable set TOOLYBARA_CLIENT_ID --org toolboxmd --repos agentsmd,marketplace --body "$TOOLYBARA_CLIENT_ID"',
        "gh secret set TOOLYBARA_PRIVATE_KEY --org toolboxmd --repos agentsmd,marketplace",
        "gh workflow run toolybara-bootstrap-verification.yml --repo toolboxmd/marketplace --ref main",
        'python3 "$VERIFY" compare-settings "$BEFORE_SETTINGS" "$AFTER_SETTINGS"',
        'python3 "$VERIFY" credential-metadata',
    )
    missing_wizard = [
        item for item in required_wizard_text if item not in normalized_wizard
    ]
    if missing_wizard:
        fail(f"wizard destination map drifted: {missing_wizard}")

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    required_workflow_text = (
        "if: github.ref == 'refs/heads/main'",
        f"actions/create-github-app-token@{ACTION_SHA}",
        "client-id: ${{ vars.TOOLYBARA_CLIENT_ID }}",
        "private-key: ${{ secrets.TOOLYBARA_PRIVATE_KEY }}",
        "owner: toolboxmd",
        "repositories: marketplace",
        "permission-contents: write",
        "permission-metadata: read",
        "permission-pull-requests: write",
        "persist-credentials: false",
        '"Authorization: Bearer $app_jwt"',
        '"https://api.github.com/app"',
        '"https://api.github.com/app/installations/$INSTALLATION_ID"',
        "--installation \"$RUNNER_TEMP/installation.json\"",
        "--installation-repositories \"$RUNNER_TEMP/installation-repositories.json\"",
        "--token-repositories \"$RUNNER_TEMP/token-repositories.json\"",
        "'/installation/repositories?per_page=100'",
    )
    missing = [item for item in required_workflow_text if item not in workflow]
    if missing:
        fail(f"verification workflow is missing required text: {missing}")
    token_action = f"actions/create-github-app-token@{ACTION_SHA}"
    if workflow.count(token_action) != 2:
        fail("verification workflow must mint exactly two independently scoped tokens")

    executable_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (WIZARD_PATH, WORKFLOW_PATH)
    )
    prohibited = (
        r"gh\s+repo\s+edit",
        r"gh\s+api[^\n]*(?:--method|-X)\s+(?:POST|PUT|PATCH|DELETE)[^\n]*(?:protection|rulesets)",
    )
    mutations = sum(bool(re.search(pattern, executable_text)) for pattern in prohibited)
    if mutations:
        fail("bootstrap contains a prohibited repository-settings mutation")

    qualified_repositories = set(
        re.findall(
            r"(?<!organizations/)toolboxmd/([a-z][a-z0-9._-]+)", executable_text
        )
    )
    selected_lists = re.findall(
        r"--repos\s+([a-z0-9._,-]+)", normalized_wizard
    ) + re.findall(r"^\s*repositories:\s*([a-z0-9._,-]+)\s*$", workflow, re.MULTILINE)
    named_repositories = qualified_repositories | {
        name for selected in selected_lists for name in selected.split(",")
    }
    allowed_repositories = set(
        load_policy()["actionsCredentials"]["secret"]["repositories"]
    )
    if named_repositories != allowed_repositories:
        fail(
            "bootstrap repository destinations drifted: "
            f"{sorted(named_repositories)}"
        )

    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    credential_patterns = (
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(r"\bIv1\.[0-9A-Fa-f]{16,}\b"),
        re.compile(r"\bIv[0-9A-Za-z]{20,}\b"),
        re.compile(r"\bgh[opusr]_[0-9A-Za-z]{20,}\b"),
    )
    credential_findings: list[str] = []
    forbidden_suffixes = (".key", ".p12", ".pem", ".pfx")
    for raw_path in tracked:
        if not raw_path:
            continue
        relative = raw_path.decode()
        path = ROOT / relative
        if relative.lower().endswith(forbidden_suffixes):
            credential_findings.append(relative)
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(pattern.search(content) for pattern in credential_patterns):
            credential_findings.append(relative)
    if credential_findings:
        fail(f"tracked credential material found: {sorted(credential_findings)}")

    return {
        "librarySha256": library_sha,
        "namedRepositories": sorted(named_repositories),
        "ok": True,
        "prohibitedSettingsMutations": mutations,
        "trackedCredentialFindings": len(credential_findings),
        "stages": stages,
        "verificationWorkflow": str(WORKFLOW_PATH.relative_to(ROOT)),
    }


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def expected_settings() -> dict:
    settings = load_policy()["repositorySettings"]
    return {**settings, "schema": 1, "viewerAdmin": True}


def compare_settings(before_path: Path, after_path: Path) -> dict:
    before = load_json(before_path)
    after = load_json(after_path)
    if before != after:
        fail("settings changed during Toolybara bootstrap")
    if before != expected_settings():
        fail("settings do not match the approved unchanged baseline")
    return {"ok": True, "settingsUnchanged": True}


def verify_installation(
    app_slug: str,
    app_path: Path,
    installation_path: Path,
    installation_repositories_path: Path,
    token_repositories_path: Path,
) -> str:
    policy = load_policy()
    expected_app = policy["app"]
    app = load_json(app_path)
    app_fields = {
        "description": app.get("description"),
        "events": app.get("events"),
        "external_url": app.get("external_url"),
        "name": app.get("name"),
        "owner": app.get("owner", {}).get("login"),
        "permissions": app.get("permissions"),
        "slug": app.get("slug"),
    }
    expected_app_fields = {
        "description": expected_app["description"],
        "events": expected_app["events"],
        "external_url": expected_app["homepage"],
        "name": expected_app["name"],
        "owner": expected_app["owner"],
        "permissions": expected_app["repositoryPermissions"],
        "slug": expected_app["slug"],
    }
    if app_fields != expected_app_fields:
        fail("registered App metadata or permission inventory drifted")
    installation = load_json(installation_path)
    if (
        app_slug != policy["app"]["slug"]
        or installation.get("app_slug") != app_slug
    ):
        fail("authenticated App slug drifted")
    if installation.get("account", {}).get("login") != policy["app"]["owner"]:
        fail("installation owner drifted")
    if installation.get("target_type") != "Organization":
        fail("installation target type drifted")
    if installation.get("events") != expected_app["events"]:
        fail("installation event subscriptions drifted")
    if installation.get("repository_selection") != policy["installation"][
        "repositorySelection"
    ]:
        fail("installation repository selection drifted")
    permissions = installation.get("permissions")
    if permissions != policy["app"]["repositoryPermissions"]:
        fail("installation permission inventory drifted")
    expected = [
        f"{policy['installation']['owner']}/{name}"
        for name in policy["installation"]["repositories"]
    ]
    installation_repositories_document = load_json(installation_repositories_path)
    installation_repositories = sorted(
        item["full_name"]
        for item in installation_repositories_document.get("repositories", [])
    )
    if (
        installation_repositories_document.get("total_count") != len(expected)
        or installation_repositories != expected
    ):
        fail("installation repository scope drifted")
    token_repositories_document = load_json(token_repositories_path)
    token_repositories = sorted(
        item["full_name"] for item in token_repositories_document.get("repositories", [])
    )
    if (
        token_repositories_document.get("total_count") != len(expected)
        or token_repositories != expected
    ):
        fail("Marketplace token repository scope drifted")
    return "\n".join(
        (
            "### Toolybara bootstrap verification",
            "",
            f"- Actor: `{policy['app']['actor']}`",
            f"- App slug: `{app_slug}`",
            "- Registered App metadata and permissions: exact policy match",
            f"- Installation repository scope: `{installation_repositories[0]}`",
            f"- Marketplace token scope: `{token_repositories[0]}`",
            "- Token permissions: "
            + ", ".join(f"`{name}: {level}`" for name, level in permissions.items()),
            "- Token use: read-only verification; token revoked after the job",
        )
    ) + "\n"


def gh_api(endpoint: str, *, allow_not_found: bool = False) -> dict | list | None:
    result = subprocess.run(
        ["gh", "api", endpoint],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        not_found = '"status":"404"' in result.stdout.replace(" ", "")
        not_found = not_found or "HTTP 404" in result.stderr
        if allow_not_found and not_found:
            return None
        fail(f"GitHub API read failed for {endpoint}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def gh_endpoint_exists(endpoint: str) -> bool:
    result = subprocess.run(
        ["gh", "api", "--silent", endpoint],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode == 0:
        return True
    if "HTTP 404" in result.stderr:
        return False
    fail(f"GitHub API read failed for {endpoint}: {result.stderr.strip()}")


def capture_settings() -> dict:
    repository = gh_api("repos/toolboxmd/marketplace")
    if not isinstance(repository, dict):
        fail("unexpected Marketplace repository response")
    if not repository.get("permissions", {}).get("admin"):
        fail("admin access is required to disambiguate settings evidence")
    protection = gh_api(
        "repos/toolboxmd/marketplace/branches/main/protection",
        allow_not_found=True,
    )
    rulesets = gh_api("repos/toolboxmd/marketplace/rulesets")
    if not isinstance(rulesets, list):
        fail("unexpected Marketplace rulesets response")
    required_status_checks = False
    blocked_direct_pushes = False
    force_pushes_blocked = False
    bypass_actors: list[str] = []
    if isinstance(protection, dict):
        required_status_checks = protection.get("required_status_checks") is not None
        pull_request_reviews = protection.get("required_pull_request_reviews")
        blocked_direct_pushes = pull_request_reviews is not None
        force_pushes_blocked = not protection.get("allow_force_pushes", {}).get(
            "enabled", False
        )
        allowances = (pull_request_reviews or {}).get(
            "bypass_pull_request_allowances", {}
        )
        for kind in ("users", "teams", "apps"):
            for actor in allowances.get(kind, []):
                label = actor.get("slug") or actor.get("login") or actor.get("name")
                if label:
                    bypass_actors.append(f"{kind}:{label}")
    return {
        "allowAutoMerge": repository["allow_auto_merge"],
        "blockedDirectPushes": blocked_direct_pushes,
        "branchProtection": protection is not None,
        "bypassActors": sorted(bypass_actors),
        "defaultBranch": repository["default_branch"],
        "deleteBranchOnMerge": repository["delete_branch_on_merge"],
        "forcePushesBlocked": force_pushes_blocked,
        "repository": repository["full_name"],
        "requiredStatusChecks": required_status_checks,
        "rulesets": rulesets,
        "schema": 1,
        "viewerAdmin": True,
    }


def credential_metadata() -> dict:
    policy = load_policy()
    result: dict[str, dict] = {}
    for kind, endpoint_kind in (("variable", "variables"), ("secret", "secrets")):
        item = policy["actionsCredentials"][kind]
        name = item["name"]
        metadata = gh_api(f"orgs/toolboxmd/actions/{endpoint_kind}/{name}")
        selected = gh_api(
            f"orgs/toolboxmd/actions/{endpoint_kind}/{name}/repositories?per_page=100"
        )
        if not isinstance(metadata, dict) or not isinstance(selected, dict):
            fail(f"unexpected {kind} metadata response")
        repositories = sorted(
            repository["name"] for repository in selected.get("repositories", [])
        )
        if (
            metadata.get("visibility") != "selected"
            or selected.get("total_count") != len(item["repositories"])
            or repositories != item["repositories"]
        ):
            fail(f"{kind} repository selection drifted")
        if kind == "secret" and "value" in metadata:
            fail("secret metadata unexpectedly exposed a value")
        copies = []
        for repository in item["repositories"]:
            endpoint = f"repos/toolboxmd/{repository}/actions/{endpoint_kind}/{name}"
            if gh_endpoint_exists(endpoint):
                copies.append(f"toolboxmd/{repository}")
        if copies:
            fail(f"{kind} repository-level copy exists: {copies}")
        result[kind] = {
            "name": name,
            "repositories": repositories,
            "repositoryCopies": copies,
            "valueExposed": "value" in metadata,
            "visibility": metadata["visibility"],
        }
    return {"ok": True, **result}


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("policy")
    subparsers.add_parser("static")
    compare = subparsers.add_parser("compare-settings")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    installation = subparsers.add_parser("verify-installation")
    installation.add_argument("--app-slug", required=True)
    installation.add_argument("--app", required=True, type=Path)
    installation.add_argument("--installation", required=True, type=Path)
    installation.add_argument(
        "--installation-repositories", required=True, type=Path
    )
    installation.add_argument("--token-repositories", required=True, type=Path)
    subparsers.add_parser("capture-settings")
    subparsers.add_parser("credential-metadata")
    args = parser.parse_args()
    if args.command == "policy":
        print(json.dumps(policy_summary(load_policy()), indent=2, sort_keys=True))
    elif args.command == "static":
        print(json.dumps(verify_static(), indent=2, sort_keys=True))
    elif args.command == "compare-settings":
        print(
            json.dumps(
                compare_settings(args.before, args.after), indent=2, sort_keys=True
            )
        )
    elif args.command == "verify-installation":
        print(
            verify_installation(
                args.app_slug,
                args.app,
                args.installation,
                args.installation_repositories,
                args.token_repositories,
            ),
            end="",
        )
    elif args.command == "capture-settings":
        print(json.dumps(capture_settings(), indent=2, sort_keys=True))
    elif args.command == "credential-metadata":
        print(json.dumps(credential_metadata(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
