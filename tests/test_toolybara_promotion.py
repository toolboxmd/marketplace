#!/usr/bin/env python3
"""Toolybara promotion tests at the reconciliation and trusted-merge seams."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROMOTION = ROOT / "scripts" / "toolybara_promotion.py"
WORKFLOW = ROOT / ".github" / "workflows" / "toolybara-reconciliation.yml"
SPEC = importlib.util.spec_from_file_location("toolybara_promotion", PROMOTION)
assert SPEC and SPEC.loader
promotion = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(promotion)


class ReleaseSelectionTests(unittest.TestCase):
    @patch.object(promotion, "_gh_request")
    def test_release_discovery_paginates_to_exhaustion(self, request) -> None:
        first = [
            {"tag_name": f"v7.0.{patch_number}", "draft": False, "prerelease": False}
            for patch_number in range(100)
        ]
        newest = {"tag_name": "v8.6.0", "draft": False, "prerelease": False}
        request.side_effect = [first, [newest]]

        self.assertEqual(promotion._published_releases(), [*first, newest])
        self.assertEqual(
            [call.args[1] for call in request.call_args_list],
            [
                "/repos/toolboxmd/agentsmd/releases?per_page=100&page=1",
                "/repos/toolboxmd/agentsmd/releases?per_page=100&page=2",
            ],
        )

    def test_wake_hint_cannot_override_the_newest_valid_release(self) -> None:
        releases = [
            {"tag_name": "v8.5.1", "draft": False, "prerelease": False},
            {"tag_name": "v8.6.0", "draft": False, "prerelease": False},
        ]

        decision = promotion.select_candidate(
            releases,
            current_tag="v5.1.0",
            wake_tag="v8.5.1",
            inspect=lambda tag: {"release": tag, "commit": tag.removeprefix("v")},
        )

        self.assertEqual(decision.state, "candidate")
        self.assertEqual(decision.candidate["release"], "v8.6.0")
        self.assertEqual(decision.wake_tag, "v8.5.1")

    def test_invalid_unreconciled_release_is_actionable_not_duplicate(self) -> None:
        def reject(tag: str) -> dict:
            raise promotion.PromotionError(f"missing Project Record in {tag}")

        decision = promotion.select_candidate(
            [{"tag_name": "v8.6.0", "draft": False, "prerelease": False}],
            current_tag="v8.5.1",
            wake_tag=None,
            inspect=reject,
        )

        self.assertEqual(decision.state, "invalid")
        self.assertIsNone(decision.candidate)
        self.assertEqual(
            decision.rejected,
            [
                {
                    "release": "v8.6.0",
                    "reason": "missing Project Record in v8.6.0",
                }
            ],
        )

    def test_duplicate_is_a_noop_and_schedule_recovers_a_missed_event(self) -> None:
        releases = [
            {"tag_name": "v8.5.1", "draft": False, "prerelease": False},
            {"tag_name": "v8.6.0", "draft": False, "prerelease": False},
        ]
        inspect = lambda tag: {"release": tag}

        duplicate = promotion.select_candidate(
            releases,
            current_tag="v8.6.0",
            wake_tag="v8.6.0",
            inspect=inspect,
        )
        missed = promotion.select_candidate(
            releases,
            current_tag="v8.5.1",
            wake_tag=None,
            inspect=inspect,
        )

        self.assertEqual(duplicate.state, "duplicate")
        self.assertIsNone(duplicate.candidate)
        self.assertEqual(missed.state, "candidate")
        self.assertEqual(missed.candidate["release"], "v8.6.0")

    def test_competing_new_release_invalidates_an_older_candidate(self) -> None:
        decision = promotion.select_candidate(
            [
                {"tag_name": "v8.6.0", "draft": False, "prerelease": False},
                {"tag_name": "v8.7.0", "draft": False, "prerelease": False},
            ],
            current_tag="v8.5.1",
            wake_tag="v8.6.0",
            inspect=lambda tag: {"release": tag},
        )

        with self.assertRaisesRegex(
            promotion.PromotionError,
            "newest eligible release changed",
        ):
            promotion.require_same_candidate(decision, "v8.6.0")


class GeneratedScopeTests(unittest.TestCase):
    def test_generated_allowlist_rejects_control_plane_and_test_changes(self) -> None:
        allowed = {
            "catalog.json",
            ".agents/plugins/marketplace.json",
            ".claude-plugin/marketplace.json",
            ".grok-plugin/marketplace.json",
            ".cursor-plugin/marketplace.json",
            "plugins/agentsmd/VERSION",
            "VERSION",
            "CHANGELOG.md",
        }
        promotion.validate_generated_paths(allowed)

        for unexpected in (
            "scripts/toolybara_promotion.py",
            "tests/test_catalog.py",
            ".github/workflows/toolybara-reconciliation.yml",
            "plugins/use-grok/SKILL.md",
        ):
            with self.subTest(unexpected=unexpected):
                with self.assertRaisesRegex(
                    promotion.PromotionError,
                    "outside generated allowlist",
                ):
                    promotion.validate_generated_paths({*allowed, unexpected})

    def test_candidate_has_one_patch_transition_and_preserves_other_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base"
            candidate = root / "candidate"
            base.mkdir()
            candidate.mkdir()
            base_catalog = {
                "plugins": [
                    {"name": "karpathy-wiki", "sha": "k" * 40},
                    {"name": "use-grok", "sha": "u" * 40},
                    {"name": "agentsmd", "release": "v8.5.1", "sha": "a" * 40},
                ]
            }
            candidate_catalog = json.loads(json.dumps(base_catalog))
            candidate_catalog["plugins"][2] = {
                "name": "agentsmd",
                "release": "v8.6.0",
                "sha": "b" * 40,
                "projectRecord": {
                    "path": ".toolboxmd/project.json",
                    "sha256": "c" * 64,
                },
            }
            for directory, version, catalog in (
                (base, "1.2.0", base_catalog),
                (candidate, "1.2.1", candidate_catalog),
            ):
                (directory / "VERSION").write_text(version + "\n", encoding="utf-8")
                (directory / "catalog.json").write_text(
                    json.dumps(catalog), encoding="utf-8"
                )
            (candidate / "CHANGELOG.md").write_text(
                "# Changelog\n\n## [1.2.1] - 2026-09-03\n",
                encoding="utf-8",
            )

            promotion.validate_candidate_state(
                base,
                candidate,
                {
                    "release": "v8.6.0",
                    "commit": "b" * 40,
                    "recordSha256": "c" * 64,
                },
            )

            candidate_catalog["plugins"][1]["sha"] = "x" * 40
            (candidate / "catalog.json").write_text(
                json.dumps(candidate_catalog), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                promotion.PromotionError,
                "non-AgentsMD catalog records changed",
            ):
                promotion.validate_candidate_state(
                    base,
                    candidate,
                    {
                        "release": "v8.6.0",
                        "commit": "b" * 40,
                        "recordSha256": "c" * 64,
                    },
                )

    def test_generation_is_idempotent_and_leaves_the_base_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            base = temp / "base"
            candidate = temp / "candidate"
            source = temp / "agentsmd"
            shutil.copytree(ROOT, base, ignore=shutil.ignore_patterns(".git"))
            shutil.copytree(ROOT / "tests" / "fixtures" / "project-record-v1", source)

            record_path = source / ".toolboxmd" / "project.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["id"] = "agentsmd"
            record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            (source / "VERSION").write_text("8.6.0\n", encoding="utf-8")
            for manifest_path in (
                ".codex-plugin/plugin.json",
                ".claude-plugin/plugin.json",
                ".grok-plugin/plugin.json",
            ):
                path = source / manifest_path
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest["name"] = "agentsmd"
                manifest["version"] = "8.6.0"
                path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            for relative in (
                "bin/versionctl",
                "tools/versionctl/bin/versionctl",
                "tools/versionctl/src/versionctl/__init__.py",
            ):
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# fixture runtime\n", encoding="utf-8")

            environment = {
                **os.environ,
                "GIT_AUTHOR_DATE": "2026-09-03T12:00:00Z",
                "GIT_COMMITTER_DATE": "2026-09-03T12:00:00Z",
            }
            for repository in (base, source):
                subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
                subprocess.run(
                    ["git", "config", "user.name", "Fixture"], cwd=repository, check=True
                )
                subprocess.run(
                    ["git", "config", "user.email", "fixture@example.com"],
                    cwd=repository,
                    check=True,
                )
                subprocess.run(["git", "add", "."], cwd=repository, check=True)
                subprocess.run(
                    ["git", "commit", "-q", "-m", "fixture base"],
                    cwd=repository,
                    check=True,
                    env=environment,
                )
            subprocess.run(
                ["git", "tag", "-a", "v8.6.0", "-m", "agentsmd v8.6.0"],
                cwd=source,
                check=True,
                env=environment,
            )
            subprocess.run(["git", "clone", "-q", str(base), str(candidate)], check=True)

            base_catalog = (base / "catalog.json").read_bytes()
            base_version = tuple(
                int(part) for part in (base / "VERSION").read_text().strip().split(".")
            )
            expected_version = (
                f"{base_version[0]}.{base_version[1]}.{base_version[2] + 1}\n"
            )
            first = promotion.build_generated_candidate(
                base_root=base,
                candidate_root=candidate,
                source_root=source,
                release="v8.6.0",
            )
            first_tree = promotion.working_tree_id(candidate)
            second = promotion.build_generated_candidate(
                base_root=base,
                candidate_root=candidate,
                source_root=source,
                release="v8.6.0",
            )

            self.assertEqual(first, second)
            self.assertEqual(promotion.working_tree_id(candidate), first_tree)
            self.assertEqual((candidate / "VERSION").read_text(), expected_version)
            self.assertEqual((base / "catalog.json").read_bytes(), base_catalog)


class TrustedPullRequestTests(unittest.TestCase):
    def test_orphan_branch_is_rewritten_with_exact_lease_before_pr_retry(self) -> None:
        pushes = []

        candidate_head = promotion.prepare_existing_branch(
            Path("/candidate"),
            previous="p" * 40,
            candidate_head="h" * 40,
            candidate_tree="t" * 40,
            base_sha="b" * 40,
            open_pull_requests=[],
            closed_pull_requests=[
                {"number": 20, "head": {"sha": "o" * 40}}
            ],
            request=lambda *_args, **_kwargs: self.fail("unexpected API read"),
            push=lambda root, branch, *, previous: pushes.append(
                (root, branch, previous)
            ),
        )

        self.assertEqual(candidate_head, "h" * 40)
        self.assertEqual(
            pushes,
            [(Path("/candidate"), "toolybara/promote-agentsmd", "p" * 40)],
        )

    def test_manual_pr_supersession_is_unmerged_exact_and_idempotent(self) -> None:
        calls = []

        def open_request(
            method: str, endpoint: str, payload: dict | None = None
        ) -> dict | list:
            calls.append((method, endpoint, payload))
            if endpoint.endswith("/pulls/15") and method == "GET":
                return {
                    "state": "closed" if open_request.closed else "open",
                    "merged": False,
                }
            if endpoint.endswith("/comments?per_page=100"):
                return []
            if endpoint.endswith("/comments"):
                return {"id": 1}
            if endpoint.endswith("/pulls/15") and method == "PATCH":
                open_request.closed = True
                return {"state": "closed", "merged": False}
            self.fail(f"unexpected request: {method} {endpoint}")

        open_request.closed = False

        promotion._supersede_manual_pr(
            21,
            "m" * 40,
            "https://github.com/toolboxmd/marketplace/releases/tag/v1.2.1",
            request=open_request,
        )
        comment_body = next(
            payload["body"]
            for method, endpoint, payload in calls
            if method == "POST" and endpoint.endswith("/comments")
        )
        self.assertIn("Toolybara-authored PR #21", comment_body)
        self.assertIn("PR #15 was a manual proposal", comment_body)
        self.assertIn("was not merged or automatic delivery", comment_body)

        closed_calls = []

        def closed_request(
            method: str, endpoint: str, payload: dict | None = None
        ) -> dict | list:
            closed_calls.append((method, endpoint, payload))
            if endpoint.endswith("/pulls/15"):
                return {"state": "closed", "merged": False}
            if endpoint.endswith("/comments?per_page=100"):
                return [{"body": comment_body}]
            self.fail(f"unexpected request: {method} {endpoint}")

        promotion._supersede_manual_pr(
            21,
            "m" * 40,
            "https://github.com/toolboxmd/marketplace/releases/tag/v1.2.1",
            request=closed_request,
        )
        self.assertEqual(len(closed_calls), 2)

        with self.assertRaisesRegex(
            promotion.PromotionError, "manual pull request #15 is not proven unmerged"
        ):
            promotion._supersede_manual_pr(
                21,
                "m" * 40,
                "https://github.com/toolboxmd/marketplace/releases/tag/v1.2.1",
                request=lambda *_args, **_kwargs: {
                    "state": "closed",
                    "merged": True,
                },
            )

        race_reads = 0

        def raced_request(
            method: str, endpoint: str, payload: dict | None = None
        ) -> dict | list:
            nonlocal race_reads
            if endpoint.endswith("/pulls/15") and method == "GET":
                race_reads += 1
                return {
                    "state": "open" if race_reads == 1 else "closed",
                    "merged": race_reads > 1,
                }
            if endpoint.endswith("/comments?per_page=100"):
                return []
            if endpoint.endswith("/comments"):
                return {"id": 1}
            if endpoint.endswith("/pulls/15") and method == "PATCH":
                return {"state": "closed", "merged": False}
            self.fail(f"unexpected request: {method} {endpoint}")

        with self.assertRaisesRegex(
            promotion.PromotionError, "is not closed and unmerged"
        ):
            promotion._supersede_manual_pr(
                21,
                "m" * 40,
                "https://github.com/toolboxmd/marketplace/releases/tag/v1.2.1",
                request=raced_request,
            )

    def test_live_snapshot_binds_actor_branch_base_and_exact_head(self) -> None:
        snapshot = {
            "number": 21,
            "state": "open",
            "draft": False,
            "user": {"login": "toolybara[bot]"},
            "head": {
                "ref": "toolybara/promote-agentsmd",
                "sha": "h" * 40,
                "repo": {"full_name": "toolboxmd/marketplace"},
            },
            "base": {"ref": "main", "sha": "b" * 40},
            "mergeable": True,
        }
        expected = {
            "number": 21,
            "head": "h" * 40,
            "base": "b" * 40,
        }
        promotion.validate_pull_request(snapshot, expected, require_mergeable=True)

        mutations = {
            "actor": ("user", {"login": "github-actions[bot]"}),
            "branch": (
                "head",
                {
                    "ref": "feature/other",
                    "sha": "h" * 40,
                    "repo": {"full_name": "toolboxmd/marketplace"},
                },
            ),
            "competing-head": (
                "head",
                {
                    "ref": "toolybara/promote-agentsmd",
                    "sha": "x" * 40,
                    "repo": {"full_name": "toolboxmd/marketplace"},
                },
            ),
            "stale-base": ("base", {"ref": "main", "sha": "x" * 40}),
            "unmergeable": ("mergeable", False),
        }
        for case, (field, value) in mutations.items():
            with self.subTest(case=case):
                changed = json.loads(json.dumps(snapshot))
                changed[field] = value
                with self.assertRaises(promotion.PromotionError):
                    promotion.validate_pull_request(
                        changed,
                        expected,
                        require_mergeable=True,
                    )

    def test_finalization_can_resume_only_the_same_already_merged_candidate(self) -> None:
        snapshot = {
            "number": 21,
            "state": "closed",
            "draft": False,
            "merged": True,
            "merged_by": {"login": "toolybara[bot]"},
            "merge_commit_sha": "m" * 40,
            "user": {"login": "toolybara[bot]"},
            "head": {
                "ref": "toolybara/promote-agentsmd",
                "sha": "h" * 40,
                "repo": {"full_name": "toolboxmd/marketplace"},
            },
            "base": {"ref": "main", "sha": "b" * 40},
            "mergeable": None,
        }
        expected = {
            "number": 21,
            "head": "h" * 40,
            "base": "b" * 40,
        }

        promotion.validate_pull_request(
            snapshot,
            expected,
            require_mergeable=False,
            allow_merged=True,
        )
        snapshot["merged"] = False
        with self.assertRaises(promotion.PromotionError):
            promotion.validate_pull_request(
                snapshot,
                expected,
                require_mergeable=False,
                allow_merged=True,
            )
        snapshot["merged"] = True
        snapshot["merged_by"]["login"] = "human-user"
        with self.assertRaisesRegex(
            promotion.PromotionError, "was not finalized by Toolybara"
        ):
            promotion.validate_pull_request(
                snapshot,
                expected,
                require_mergeable=False,
                allow_merged=True,
            )

    def test_moved_base_merge_is_fully_revalidated_before_release(self) -> None:
        args = type("Args", (), {"base_sha": "b" * 40})()
        candidate = {"tree": {"sha": "t" * 40}}
        drift_calls = []

        exact = promotion.validate_merged_result(
            args,
            {
                "parents": [{"sha": "b" * 40}],
                "tree": {"sha": "t" * 40},
            },
            candidate,
            validate_drift=lambda actual_base: drift_calls.append(actual_base),
        )
        self.assertIsNone(exact)
        self.assertEqual(drift_calls, [])

        drifted = promotion.validate_merged_result(
            args,
            {
                "parents": [{"sha": "n" * 40}],
                "tree": {"sha": "u" * 40},
            },
            candidate,
            validate_drift=lambda actual_base: {
                "actualMergeBase": actual_base,
                "validated": True,
            },
        )
        self.assertEqual(
            drifted,
            {"actualMergeBase": "n" * 40, "validated": True},
        )

        with self.assertRaisesRegex(promotion.PromotionError, "merged tree differs"):
            promotion.validate_merged_result(
                args,
                {
                    "parents": [{"sha": "b" * 40}],
                    "tree": {"sha": "u" * 40},
                },
                candidate,
                validate_drift=lambda _actual_base: self.fail(
                    "unexpected drift validation"
                ),
            )

    def test_retained_branch_can_only_follow_a_merged_toolybara_pr(self) -> None:
        previous = {
            "state": "closed",
            "merged": True,
            "merged_by": {"login": "toolybara[bot]"},
            "user": {"login": "toolybara[bot]"},
            "head": {
                "ref": "toolybara/promote-agentsmd",
                "sha": "h" * 40,
                "repo": {"full_name": "toolboxmd/marketplace"},
            },
            "base": {"ref": "main"},
        }
        promotion.validate_previous_promotion(previous, "h" * 40)

        previous["user"]["login"] = "human-user"
        with self.assertRaises(promotion.PromotionError):
            promotion.validate_previous_promotion(previous, "h" * 40)
        previous["user"]["login"] = "toolybara[bot]"
        previous["merged_by"]["login"] = "human-user"
        with self.assertRaises(promotion.PromotionError):
            promotion.validate_previous_promotion(previous, "h" * 40)

    def test_merge_api_is_sha_bound_and_rejects_a_failed_merge(self) -> None:
        calls = []

        def request(method: str, endpoint: str, payload: dict) -> dict:
            calls.append((method, endpoint, payload))
            return {"merged": True, "sha": "m" * 40}

        merge_sha = promotion.merge_exact_head(21, "h" * 40, request=request)

        self.assertEqual(merge_sha, "m" * 40)
        self.assertEqual(
            calls,
            [
                (
                    "PUT",
                    "/repos/toolboxmd/marketplace/pulls/21/merge",
                    {"merge_method": "squash", "sha": "h" * 40},
                )
            ],
        )

        with self.assertRaisesRegex(promotion.PromotionError, "merge rejected"):
            promotion.merge_exact_head(
                21,
                "h" * 40,
                request=lambda *_: {"merged": False, "message": "Head branch was modified"},
            )

    def test_release_api_creates_an_annotated_exact_commit_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp)
            (candidate / "CHANGELOG.md").write_text(
                "# Changelog\n\n## [1.2.1] - 2026-09-03\n\n### Changed\n\n- Promote.\n",
                encoding="utf-8",
            )
            calls = []

            def request(
                method: str,
                endpoint: str,
                payload: dict | None = None,
                *,
                allow_not_found: bool = False,
            ) -> dict | None:
                calls.append((method, endpoint, payload, allow_not_found))
                if endpoint.endswith("/git/ref/tags/v1.2.1"):
                    return None
                if endpoint.endswith("/commits/" + "m" * 40):
                    return {"commit": {"committer": {"date": "2026-09-03T12:00:00Z"}}}
                if endpoint.endswith("/git/tags") and method == "POST":
                    return {"sha": "t" * 40}
                if endpoint.endswith("/git/refs"):
                    return {"object": {"sha": "t" * 40}}
                if endpoint.endswith("/git/tags/" + "t" * 40):
                    return {"object": {"sha": "m" * 40}}
                if endpoint.endswith("/releases/tags/v1.2.1"):
                    return None
                if endpoint.endswith("/releases") and method == "POST":
                    return {
                        "tag_name": "v1.2.1",
                        "draft": False,
                        "prerelease": False,
                        "html_url": "https://github.com/toolboxmd/marketplace/releases/tag/v1.2.1",
                    }
                self.fail(f"unexpected request: {method} {endpoint}")

            release = promotion.ensure_release(
                "1.2.1",
                "m" * 40,
                candidate,
                request=request,
            )

            self.assertEqual(release["tag_name"], "v1.2.1")
            tag_payload = next(payload for method, endpoint, payload, _ in calls if endpoint.endswith("/git/tags") and method == "POST")
            self.assertEqual(tag_payload["object"], "m" * 40)
            self.assertEqual(tag_payload["type"], "commit")

    def test_existing_release_must_be_public_and_exactly_tagged(self) -> None:
        def request_for(release: dict, target: str = "m" * 40):
            def request(
                method: str,
                endpoint: str,
                payload: dict | None = None,
                *,
                allow_not_found: bool = False,
            ) -> dict:
                if endpoint.endswith("/git/ref/tags/v1.2.1"):
                    return {"object": {"sha": "t" * 40}}
                if endpoint.endswith("/git/tags/" + "t" * 40):
                    return {"object": {"sha": target}}
                if endpoint.endswith("/releases/tags/v1.2.1"):
                    return release
                self.fail(f"unexpected request: {method} {endpoint}")

            return request

        public = {
            "tag_name": "v1.2.1",
            "draft": False,
            "prerelease": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = promotion.ensure_release(
                "1.2.1", "m" * 40, Path(tmp), request=request_for(public)
            )
            self.assertEqual(result, public)

            for invalid in (
                {**public, "draft": True},
                {**public, "prerelease": True},
                {**public, "tag_name": "v1.2.0"},
            ):
                with self.subTest(invalid=invalid):
                    with self.assertRaisesRegex(
                        promotion.PromotionError,
                        "GitHub Release identity is invalid",
                    ):
                        promotion.ensure_release(
                            "1.2.1",
                            "m" * 40,
                            Path(tmp),
                            request=request_for(invalid),
                        )
            with self.assertRaisesRegex(
                promotion.PromotionError,
                "does not point to the exact merge commit",
            ):
                promotion.ensure_release(
                    "1.2.1",
                    "m" * 40,
                    Path(tmp),
                    request=request_for(public, "x" * 40),
                )


class WorkflowContractTests(unittest.TestCase):
    def test_receiver_is_event_driven_scheduled_serialized_and_trusted(self) -> None:
        self.assertFalse((WORKFLOW.parent / "toolybara-promotion.yml").exists())
        workflow = WORKFLOW.read_text(encoding="utf-8")
        executable = workflow + PROMOTION.read_text(encoding="utf-8")
        required = (
            "repository_dispatch:",
            "agentsmd_release_published",
            "schedule:",
            "cron: '43 * * * *'",
            "workflow_dispatch:",
            "group: toolybara-agentsmd-promotion",
            "cancel-in-progress: false",
            "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803",
            "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1",
            "persist-credentials: false",
            "jobs:",
            "reconcile:",
            "validate:",
            "finalize:",
            "permission-contents: write",
            "permission-pull-requests: write",
            "test \"$APP_SLUG\" = \"toolybara\"",
            "READ_TOKEN: ${{ github.token }}",
            "TOOLYBARA_TOKEN: ${{ steps.toolybara.outputs.token }}",
            "--require-mergeable",
        )
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, workflow)
        for prohibited in (
            "pull_request_target",
            "enablePullRequestAutoMerge",
            "gh pr merge --auto",
            "/protection",
            "/rulesets",
            "/actions/permissions",
            "allow_auto_merge",
            "delete_branch_on_merge",
        ):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, executable)
        version_policy = json.loads((ROOT / ".version-policy.json").read_text())
        self.assertEqual(version_policy["githubReleasePolicy"], "on-version-commit")


if __name__ == "__main__":
    unittest.main(verbosity=2)
