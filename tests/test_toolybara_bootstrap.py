#!/usr/bin/env python3
"""Toolybara bootstrap tests at the public verifier and wizard seams."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify_toolybara_bootstrap.py"
SPEC = importlib.util.spec_from_file_location("toolybara_verifier", VERIFY)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class ToolybaraBootstrapTests(unittest.TestCase):
    def test_private_key_files_are_ignored_and_absent(self) -> None:
        self.assertIn("*.pem", (ROOT / ".gitignore").read_text(encoding="utf-8"))
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertFalse([path for path in tracked if path.endswith(".pem")])

    def test_policy_is_the_approved_least_authority_contract(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VERIFY), "policy"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            json.loads(result.stdout),
            {
                "actor": "toolybara[bot]",
                "appInstallationRepositories": ["marketplace"],
                "appPermissions": {
                    "contents": "write",
                    "metadata": "read",
                    "pull_requests": "write",
                },
                "credentialRepositories": ["agentsmd", "marketplace"],
                "repositorySettings": {
                    "allowAutoMerge": False,
                    "blockedDirectPushes": False,
                    "branchProtection": False,
                    "bypassActors": [],
                    "defaultBranch": "main",
                    "deleteBranchOnMerge": False,
                    "forcePushesBlocked": False,
                    "repository": "toolboxmd/marketplace",
                    "requiredStatusChecks": False,
                    "rulesets": [],
                },
                "secret": "TOOLYBARA_PRIVATE_KEY",
                "variable": "TOOLYBARA_CLIENT_ID",
            },
        )

    def test_static_verifier_accepts_the_guided_bootstrap(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VERIFY), "static"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            json.loads(result.stdout),
            {
                "librarySha256": (
                    "36ddf7aa3a7da152768664bddc48451a6a738f44840eb94e1c5cb014c531c02d"
                ),
                "namedRepositories": ["agentsmd", "marketplace"],
                "ok": True,
                "prohibitedSettingsMutations": 0,
                "trackedCredentialFindings": 0,
                "stages": [
                    "Preflight and settings baseline",
                    "Register Toolybara",
                    "Install on Marketplace only",
                    "Store the public client ID",
                    "Store the private key",
                    "Verify Toolybara identity and scope",
                    "Prove settings unchanged and clean up",
                ],
                "verificationWorkflow": (
                    ".github/workflows/toolybara-bootstrap-verification.yml"
                ),
            },
        )

    def test_settings_comparison_accepts_only_the_unchanged_baseline(self) -> None:
        baseline = {
            "allowAutoMerge": False,
            "blockedDirectPushes": False,
            "branchProtection": False,
            "bypassActors": [],
            "defaultBranch": "main",
            "deleteBranchOnMerge": False,
            "forcePushesBlocked": False,
            "repository": "toolboxmd/marketplace",
            "requiredStatusChecks": False,
            "rulesets": [],
            "schema": 1,
            "viewerAdmin": True,
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            before = directory / "before.json"
            after = directory / "after.json"
            before.write_text(json.dumps(baseline), encoding="utf-8")
            after.write_text(json.dumps(baseline), encoding="utf-8")

            accepted = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY),
                    "compare-settings",
                    str(before),
                    str(after),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                json.loads(accepted.stdout),
                {"ok": True, "settingsUnchanged": True},
            )

            drifted = {**baseline, "allowAutoMerge": True}
            after.write_text(json.dumps(drifted), encoding="utf-8")
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY),
                    "compare-settings",
                    str(before),
                    str(after),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("settings changed", rejected.stderr)

    def test_installation_verifier_accepts_only_toolybara_on_marketplace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / "app.json"
            installation = Path(temporary) / "installation.json"
            installation_repositories = Path(temporary) / "installation-repositories.json"
            token_repositories = Path(temporary) / "token-repositories.json"
            app.write_text(
                json.dumps(
                    {
                        "description": (
                            "The ToolboxMD release courier. Toolybara carries "
                            "verified ToolboxMD releases into the Marketplace and "
                            "merges them when every check is green."
                        ),
                        "events": [],
                        "external_url": "https://github.com/toolboxmd/marketplace",
                        "name": "Toolybara",
                        "owner": {"login": "toolboxmd"},
                        "permissions": {
                            "contents": "write",
                            "metadata": "read",
                            "pull_requests": "write",
                        },
                        "slug": "toolybara",
                    }
                ),
                encoding="utf-8",
            )
            installation.write_text(
                json.dumps(
                    {
                        "account": {"login": "toolboxmd"},
                        "app_slug": "toolybara",
                        "events": [],
                        "permissions": {
                            "contents": "write",
                            "metadata": "read",
                            "pull_requests": "write",
                        },
                        "repository_selection": "selected",
                        "target_type": "Organization",
                    }
                ),
                encoding="utf-8",
            )
            installation_repositories.write_text(
                json.dumps(
                    {
                        "total_count": 1,
                        "repositories": [
                            {"full_name": "toolboxmd/marketplace"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            token_repositories.write_text(
                installation_repositories.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            accepted = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY),
                    "verify-installation",
                    "--app-slug",
                    "toolybara",
                    "--app",
                    str(app),
                    "--installation",
                    str(installation),
                    "--installation-repositories",
                    str(installation_repositories),
                    "--token-repositories",
                    str(token_repositories),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("Actor: `toolybara[bot]`", accepted.stdout)
            self.assertIn(
                "Installation repository scope: `toolboxmd/marketplace`",
                accepted.stdout,
            )
            self.assertIn(
                "Marketplace token scope: `toolboxmd/marketplace`", accepted.stdout
            )

            overprivileged = json.loads(installation.read_text(encoding="utf-8"))
            overprivileged["permissions"]["administration"] = "write"
            installation.write_text(json.dumps(overprivileged), encoding="utf-8")
            rejected_permissions = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY),
                    "verify-installation",
                    "--app-slug",
                    "toolybara",
                    "--app",
                    str(app),
                    "--installation",
                    str(installation),
                    "--installation-repositories",
                    str(installation_repositories),
                    "--token-repositories",
                    str(token_repositories),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected_permissions.returncode, 0)
            self.assertIn("permission inventory drifted", rejected_permissions.stderr)

            del overprivileged["permissions"]["administration"]
            installation.write_text(json.dumps(overprivileged), encoding="utf-8")

            installation_repositories.write_text(
                json.dumps(
                    {
                        "total_count": 2,
                        "repositories": [
                            {"full_name": "toolboxmd/agentsmd"},
                            {"full_name": "toolboxmd/marketplace"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY),
                    "verify-installation",
                    "--app-slug",
                    "toolybara",
                    "--app",
                    str(app),
                    "--installation",
                    str(installation),
                    "--installation-repositories",
                    str(installation_repositories),
                    "--token-repositories",
                    str(token_repositories),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("installation repository scope drifted", rejected.stderr)

    def test_credential_metadata_rejects_extra_selection_and_repository_copies(self) -> None:
        def exact_api(endpoint: str, *, allow_not_found: bool = False):
            del allow_not_found
            kind = "variable" if "/variables/" in endpoint else "secret"
            if endpoint.endswith("/repositories?per_page=100"):
                return {
                    "total_count": 2,
                    "repositories": [{"name": "agentsmd"}, {"name": "marketplace"}],
                }
            return {"name": kind, "visibility": "selected"}

        with mock.patch.object(VERIFIER, "gh_api", side_effect=exact_api), mock.patch.object(
            VERIFIER, "gh_endpoint_exists", return_value=False
        ):
            result = VERIFIER.credential_metadata()
        self.assertEqual(result["secret"]["repositoryCopies"], [])
        self.assertEqual(result["variable"]["repositoryCopies"], [])

        def extra_api(endpoint: str, *, allow_not_found: bool = False):
            response = exact_api(endpoint, allow_not_found=allow_not_found)
            if endpoint.endswith("/repositories?per_page=100"):
                response["total_count"] = 3
            return response

        with mock.patch.object(VERIFIER, "gh_api", side_effect=extra_api), mock.patch.object(
            VERIFIER, "gh_endpoint_exists", return_value=False
        ):
            with self.assertRaisesRegex(SystemExit, "repository selection drifted"):
                VERIFIER.credential_metadata()

        with mock.patch.object(VERIFIER, "gh_api", side_effect=exact_api), mock.patch.object(
            VERIFIER, "gh_endpoint_exists", return_value=True
        ):
            with self.assertRaisesRegex(SystemExit, "repository-level copy exists"):
                VERIFIER.credential_metadata()


if __name__ == "__main__":
    unittest.main(verbosity=2)
