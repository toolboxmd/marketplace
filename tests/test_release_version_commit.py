#!/usr/bin/env python3
"""Version commits on main get exactly one tag and release, without live GitHub calls."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release_version_commit.py"
WORKFLOW = ROOT / ".github" / "workflows" / "release-version-commit.yml"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("release_version_commit", SCRIPT)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)

SHA = "a" * 40
REPO = "/repos/toolboxmd/marketplace"


class FakeGitHub:
    def __init__(self, documents: dict):
        self.documents = documents
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method, endpoint, payload=None, *, allow_not_found=False):
        self.calls.append((method, endpoint, payload))
        if method == "POST":
            return {
                f"{REPO}/git/tags": {"sha": "t" * 40},
                f"{REPO}/git/refs": {"object": {"sha": "t" * 40}},
                f"{REPO}/releases": {"tag_name": payload.get("tag_name"), "draft": False,
                                     "html_url": "https://example.test/release"},
                f"{REPO}/dispatches": {},
            }[endpoint]
        if endpoint in self.documents:
            return self.documents[endpoint]
        if allow_not_found:
            return None
        raise AssertionError(f"unexpected request {method} {endpoint}")

    def writes(self):
        return [(endpoint, payload) for method, endpoint, payload in self.calls if method != "GET"]


def checkout(directory: str) -> Path:
    root = Path(directory)
    (root / "VERSION").write_text("1.5.55\n")
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [1.5.55] - 2026-09-29\n\n### Fixed\n\n- Tag it\n\n## [1.5.54] - 2026-09-29\n\n- Old\n"
    )
    return root


class ReleaseVersionCommitTests(unittest.TestCase):
    def test_absent_tag_is_checked_tagged_released_and_wakes_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = checkout(directory)
            github = FakeGitHub({f"{REPO}/commits/{SHA}": {"commit": {"committer": {"date": "2026-09-29T12:00:00Z"}}}})
            checked = []
            result = release.release_version_commit(root, SHA, request=github, release_check=checked.append)
        self.assertEqual(result["state"], "released")
        self.assertEqual(checked, [root])
        writes = github.writes()
        self.assertEqual([endpoint for endpoint, _ in writes],
                         [f"{REPO}/git/tags", f"{REPO}/git/refs", f"{REPO}/releases", f"{REPO}/dispatches"])
        tag, ref, published, wake = (payload for _, payload in writes)
        self.assertEqual((tag["tag"], tag["object"], tag["type"]), ("v1.5.55", SHA, "commit"))
        self.assertEqual(ref, {"ref": "refs/tags/v1.5.55", "sha": "t" * 40})
        self.assertEqual(published["body"], "## [1.5.55] - 2026-09-29\n\n### Fixed\n\n- Tag it")
        self.assertEqual((published["draft"], published["prerelease"], published["target_commitish"]), (False, False, SHA))
        self.assertEqual(wake, {"event_type": "module_release_published"})

    def test_failed_release_check_writes_nothing(self):
        def fail(_root):
            raise release.PromotionError("release check failed")

        with tempfile.TemporaryDirectory() as directory:
            github = FakeGitHub({})
            with self.assertRaises(release.PromotionError):
                release.release_version_commit(checkout(directory), SHA, request=github, release_check=fail)
        self.assertEqual(github.writes(), [])

    def test_existing_tag_for_this_commit_skips_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            github = FakeGitHub({
                f"{REPO}/git/ref/tags/v1.5.55": {"object": {"type": "tag", "sha": "t" * 40}},
                f"{REPO}/git/tags/{'t' * 40}": {"object": {"type": "commit", "sha": SHA}},
            })
            checked = []
            result = release.release_version_commit(checkout(directory), SHA, request=github, release_check=checked.append)
        self.assertEqual(result["state"], "skipped")
        self.assertEqual(checked, [])
        self.assertEqual(github.writes(), [])

    def test_existing_tag_for_another_commit_fails_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            github = FakeGitHub({
                f"{REPO}/git/ref/tags/v1.5.55": {"object": {"type": "tag", "sha": "t" * 40}},
                f"{REPO}/git/tags/{'t' * 40}": {"object": {"type": "commit", "sha": "b" * 40}},
            })
            with self.assertRaises(release.PromotionError):
                release.release_version_commit(checkout(directory), SHA, request=github, release_check=lambda _: None)
        self.assertEqual(github.writes(), [])

    def test_workflow_runs_only_for_non_toolybara_version_pushes_to_main(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        for text in (
            "  push:\n    branches:\n      - main\n    paths:\n      - VERSION\n",
            "permissions:\n  contents: write\n",
            "if: github.actor != 'toolybara[bot]'",
            "persist-credentials: false",
            "GH_TOKEN: ${{ github.token }}",
            'python3 scripts/release_version_commit.py --sha "$GITHUB_SHA"',
        ):
            with self.subTest(text=text):
                self.assertIn(text, workflow)
        for prohibited in ("secrets.", "pull_request", "workflow_dispatch", "schedule:"):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, workflow)


if __name__ == "__main__":
    unittest.main(verbosity=2)
