#!/usr/bin/env python3
"""Exercise two released modules through real ingestion and package generation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import toolybara_promotion as promotion
from toolybara_modules import enrolled, modules


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=None).decode().strip()


def initialize(root):
    git(root, "init", "-q")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    commit(root)


def commit(root):
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD")


def source_fixture(root, project, version):
    shutil.copytree(ROOT / "tests/fixtures/project-record-v1", root)
    record_path = root / ".toolboxmd/project.json"
    record = json.loads(record_path.read_text())
    record["id"] = project
    record["outcome"] = f"Use the complete {project} package."
    record_path.write_text(json.dumps(record))
    (root / "VERSION").write_text(version + "\n")
    for relative in (".codex-plugin/plugin.json", ".claude-plugin/plugin.json", ".grok-plugin/plugin.json"):
        path = root / relative
        data = json.loads(path.read_text())
        data.update(name=project, version=version)
        path.write_text(json.dumps(data))
    if project == "agentsmd":
        for directory in ("bin", "tools"):
            shutil.copytree(ROOT / "cursor/agentsmd" / directory, root / directory)
    else:
        (root / "bin").mkdir()
        launcher = root / "bin/model-router"
        launcher.write_text("#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1]))\nimport runner\nprint(runner.result)\n")
        launcher.chmod(0o755)
        (root / "runner").mkdir()
        (root / "runner/__init__.py").write_text("result = 'bundled runtime works'\n")
    initialize(root)
    git(root, "tag", "-a", "v" + version, "-m", "Fixture release")
    return root


class ModulePromotionTests(unittest.TestCase):
    def setUp(self):
        # Fixture repositories are deleted immediately. Background maintenance
        # can race their local clones or recreate pack files during cleanup.
        count = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
        git_config = {"GIT_CONFIG_COUNT": str(count + 2)}
        for offset, (key, value) in enumerate((("maintenance.auto", "false"), ("gc.auto", "0"))):
            git_config[f"GIT_CONFIG_KEY_{count + offset}"] = key
            git_config[f"GIT_CONFIG_VALUE_{count + offset}"] = value
        self.enterContext(patch.dict(os.environ, git_config))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "base"
        shutil.copytree(ROOT, self.base, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        # The suite must also work inside an already promoted candidate.
        catalog = json.loads((self.base / "catalog.json").read_text())
        catalog["plugins"] = [p for p in catalog["plugins"] if p["name"] != "model-router"]
        (self.base / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
        index = self.base / ".cursor-plugin/marketplace.json"
        data = json.loads(index.read_text())
        data["plugins"] = [p for p in data["plugins"] if p["name"] != "model-router"]
        index.write_text(json.dumps(data, indent=2) + "\n")
        shutil.rmtree(self.base / "cursor/model-router", ignore_errors=True)
        initialize(self.base)
        self.tag_base(self.base)
        self.router = source_fixture(self.root / "router", "model-router", "0.1.0")

    def tag_base(self, root):
        git(root, "tag", "-a", "v" + (root / "VERSION").read_text().strip(), "-m", "Published base")

    def promote(self, base, project, source, release, name):
        candidate = self.root / name
        git(self.root, "clone", "-q", str(base), str(candidate))
        kwargs = dict(base_root=base, candidate_root=candidate, source_root=source, release=release, project=project)
        before = promotion.working_tree_id(base)
        first = promotion.build_generated_candidate(**kwargs)
        self.assertEqual(first, promotion.build_generated_candidate(**kwargs))
        self.assertEqual(before, promotion.working_tree_id(base))
        promotion._regenerate_and_compare(base, candidate, source, first)
        return candidate, first

    def test_first_release_bundles_runtime_then_agentsmd_update_preserves_it(self):
        initial = promotion._catalog_by_name(self.base)
        candidate, receipt = self.promote(self.base, "model-router", self.router, "v0.1.0", "first")
        subprocess.run([sys.executable, str(candidate / "tests/test_catalog.py")], check=True)
        catalog = promotion._catalog_by_name(candidate)
        self.assertEqual({k: v for k, v in catalog.items() if k != "model-router"}, initial)
        self.assertEqual(catalog["model-router"]["github"], "toolboxmd/model-router")
        index = json.loads((candidate / ".cursor-plugin/marketplace.json").read_text())
        self.assertEqual([p["name"] for p in index["plugins"]], ["agentsmd", "model-router"])
        output = subprocess.check_output([str(candidate / "cursor/model-router/bin/model-router")], cwd=self.root).decode().strip()
        self.assertEqual(output, "bundled runtime works")
        preserved = promotion.working_tree_id(candidate)  # Generation above remains deterministic.
        self.assertEqual(receipt["tree"], preserved)
        git(candidate, "config", "user.name", "Fixture")
        git(candidate, "config", "user.email", "fixture@example.invalid")
        commit(candidate)
        self.tag_base(candidate)
        agents = source_fixture(self.root / "agents", "agentsmd", "99.0.0")
        second, _ = self.promote(candidate, "agentsmd", agents, "v99.0.0", "second")
        self.assertEqual(promotion._catalog_by_name(second)["model-router"], catalog["model-router"])
        self.assertEqual((second / "cursor/model-router/SOURCE.json").read_bytes(),
                         (candidate / "cursor/model-router/SOURCE.json").read_bytes())
        self.assertEqual([p["name"] for p in json.loads((second / ".cursor-plugin/marketplace.json").read_text())["plugins"]],
                         ["agentsmd", "model-router"])

    def test_native_only_module_does_not_change_cursor_distribution(self):
        policy_path = self.base / "toolybara/modules.json"
        policy = json.loads(policy_path.read_text())
        policy["modules"][1].update(cursor=False, cursorRuntime=[])
        policy_path.write_text(json.dumps(policy))
        commit(self.base)
        candidate, source = self.promote(self.base, "model-router", self.router, "v0.1.0", "native-only")
        self.assertFalse((candidate / "cursor/model-router").exists())
        self.assertEqual((candidate / ".cursor-plugin/marketplace.json").read_bytes(),
                         (self.base / ".cursor-plugin/marketplace.json").read_bytes())
        evidence = promotion.accepted_duplicate_evidence(candidate, source, base_sha="b" * 40)
        self.assertEqual(evidence["state"], "duplicate")

    def test_selected_module_rejects_other_package_and_catalog_changes(self):
        candidate, source = self.promote(self.base, "model-router", self.router, "v0.1.0", "candidate")
        with self.assertRaisesRegex(promotion.PromotionError, "allowlist"):
            promotion.validate_generated_paths({"cursor/agentsmd/VERSION"}, "model-router")
        catalog = json.loads((candidate / "catalog.json").read_text())
        catalog["plugins"][0]["sha"] = "f" * 40
        (candidate / "catalog.json").write_text(json.dumps(catalog))
        with self.assertRaisesRegex(promotion.PromotionError, "non-model-router"):
            promotion.validate_candidate_state(self.base, candidate, source)
        with self.assertRaisesRegex(ValueError, "not enrolled"):
            promotion.build_generated_candidate(base_root=self.base, candidate_root=candidate,
                source_root=self.router, release="v0.1.0", project="unapproved")

    def test_pending_module_does_not_publish_and_invalid_module_does_not_block_another(self):
        args = Namespace(project="model-router", wake_tag="v999.0.0", summary=None)
        before = promotion.working_tree_id(self.base)
        with patch.object(promotion, "_published_releases", return_value=[]), patch.object(promotion, "_clone"):
            selected, observations = promotion.discover_modules(self.base, self.root, args, "b" * 40)
        self.assertIsNone(selected)
        self.assertEqual(observations, [{"state": "pending", "project": "model-router"}])
        self.assertEqual(before, promotion.working_tree_id(self.base))
        args.project = None
        def releases(repository):
            return [{"tag_name": "v99.0.0" if repository.endswith("agentsmd") else "v0.1.0"}]
        def clone(url, destination):
            if url.endswith("model-router.git"):
                git(self.root, "clone", "-q", str(self.router), str(destination))
            else:
                destination.mkdir()  # Invalid source cannot produce a release.
        with patch.object(promotion, "_published_releases", side_effect=releases), patch.object(promotion, "_clone", side_effect=clone):
            selected, _ = promotion.discover_modules(self.base, self.root, args, "b" * 40)
        self.assertEqual(selected[0]["id"], "model-router")
        self.assertEqual(selected[2].candidate["release"], "v0.1.0")

    def test_pull_request_branch_is_bound_to_selected_project(self):
        snapshot = {"number": 70, "state": "open", "draft": False, "user": {"login": "toolybara[bot]"},
                    "head": {"ref": "toolybara/promote-model-router", "sha": "h" * 40,
                             "repo": {"full_name": "toolboxmd/marketplace"}},
                    "base": {"ref": "main", "sha": "b" * 40}, "mergeable": True}
        expected = {"project": "model-router", "number": 70, "head": "h" * 40, "base": "b" * 40}
        promotion.validate_pull_request(snapshot, expected, require_mergeable=True)
        with self.assertRaises(promotion.PromotionError):
            promotion.validate_pull_request(snapshot, {**expected, "project": "agentsmd"}, require_mergeable=True)

    def test_failed_first_module_does_not_starve_next_workflow_run(self):
        agents = source_fixture(self.root / "agents", "agentsmd", "99.0.0")
        base_sha = git(self.base, "rev-parse", "HEAD")
        args = Namespace(project=None, wake_tag="", output=None, summary=None, proof_output=None)
        actual_build = promotion.build_generated_candidate
        pushed = []

        def clone(url, destination, **kwargs):
            source = {"agentsmd.git": agents, "model-router.git": self.router,
                      "marketplace.git": self.base}[url.rsplit("/", 1)[-1]]
            git(self.root, "clone", "-q", str(source), str(destination))

        def build(**kwargs):
            if kwargs["project"] == "agentsmd":
                raise promotion.PromotionError("fixture Cursor generation failure")
            return actual_build(**kwargs)

        def push(root, branch, **kwargs):
            pushed.append((branch, git(root, "rev-parse", "HEAD")))

        def request(method, endpoint, payload=None, **kwargs):
            if method == "GET":
                return None
            self.assertEqual(method, "POST")
            self.assertEqual(payload["head"], "toolybara/promote-model-router")
            return {"number": 70, "state": "open", "draft": False,
                    "user": {"login": "toolybara[bot]"},
                    "head": {"ref": pushed[-1][0], "sha": pushed[-1][1],
                             "repo": {"full_name": "toolboxmd/marketplace"}},
                    "base": {"ref": "main", "sha": base_sha}}

        adapter = Mock()
        adapter.record.return_value = {"sha256": "a" * 64}
        with (patch.object(promotion, "__file__", str(self.base / "scripts/toolybara_promotion.py")),
              patch.object(promotion, "_main_sha", return_value=base_sha),
              patch.object(promotion, "base_release_ready", return_value=True),
              patch.object(promotion, "_clone", side_effect=clone),
              patch.object(promotion, "_published_releases", side_effect=lambda repo: [
                  {"tag_name": "v99.0.0" if repo.endswith("agentsmd") else "v0.1.0"}]),
              patch.object(promotion, "build_generated_candidate", side_effect=build),
              patch.object(promotion, "_proof_adapter", return_value=adapter),
              patch.object(promotion, "_fresh_source"),
              patch.object(promotion, "_expected_pull_requests", return_value=[]),
              patch.object(promotion, "_gh_request", side_effect=request),
              patch.object(promotion, "_push", side_effect=push),
              patch.dict(os.environ, GH_TOKEN="fixture", GITHUB_RUN_NUMBER="1", GITHUB_RUN_ATTEMPT="1")):
            with self.assertRaisesRegex(promotion.PromotionError, "Cursor generation failure"):
                promotion.reconcile(args)
            self.assertEqual(pushed, [])
            # Retrying the same workflow keeps its order; a new run advances it.
            with patch.dict(os.environ, GITHUB_RUN_ATTEMPT="2"):
                with self.assertRaisesRegex(promotion.PromotionError, "Cursor generation failure"):
                    promotion.reconcile(args)
            with patch.dict(os.environ, GITHUB_RUN_NUMBER="2", GITHUB_RUN_ATTEMPT="1"):
                result = promotion.reconcile(args)
        self.assertEqual((result["state"], result["project"]), ("candidate", "model-router"))
        self.assertEqual(len(pushed), 1)
        adapter.record.assert_called_once()

    def test_stale_base_open_pr_is_closed_and_superseded_by_fresh_pr(self):
        base_sha = git(self.base, "rev-parse", "HEAD")
        previous = "p" * 40
        stale_base = "a" * 40
        stale = {"number": 65, "state": "open", "draft": False,
                 "user": {"login": "toolybara[bot]"},
                 "head": {"ref": "toolybara/promote-model-router", "sha": previous,
                          "repo": {"full_name": "toolboxmd/marketplace"}},
                 "base": {"ref": "main", "sha": stale_base}}
        closed = {**json.loads(json.dumps(stale)),
                  "state": "closed", "merged": False}
        calls = []
        pushed = []

        def clone(url, destination, **kwargs):
            source = {"model-router.git": self.router,
                      "marketplace.git": self.base}[url.rsplit("/", 1)[-1]]
            git(self.root, "clone", "-q", str(source), str(destination))

        def push(root, branch, **kwargs):
            head = git(root, "rev-parse", "HEAD")
            pushed.append((branch, head))
            calls.append(("push", branch, head))

        def request(method, endpoint, payload=None, **kwargs):
            calls.append((method, endpoint, payload))
            if method == "GET" and endpoint.endswith(
                    "/git/ref/heads/toolybara%2Fpromote-model-router"):
                return {"object": {"sha": previous}}
            if method == "GET" and endpoint.endswith("/pulls/65"):
                return json.loads(json.dumps(stale))
            if method == "PATCH" and endpoint.endswith("/pulls/65"):
                if payload == {"state": "closed"}:
                    return json.loads(json.dumps(closed))
                # GitHub pins a pull request's base at creation: retitling
                # the stale PR never moves its base to current main.
                return json.loads(json.dumps(stale))
            if method == "POST" and endpoint.endswith("/pulls"):
                self.assertEqual(payload["head"], "toolybara/promote-model-router")
                self.assertEqual(payload["base"], "main")
                return {"number": 71, "state": "open", "draft": False,
                        "user": {"login": "toolybara[bot]"},
                        "head": {"ref": pushed[-1][0], "sha": pushed[-1][1],
                                 "repo": {"full_name": "toolboxmd/marketplace"}},
                        "base": {"ref": "main", "sha": base_sha}}
            if method == "GET" and "/git/commits/" in endpoint:
                return {"tree": {"sha": "r" * 40}}
            self.fail(f"unexpected request: {method} {endpoint}")

        adapter = Mock()
        adapter.record.return_value = {"sha256": "a" * 64}
        args = Namespace(project="model-router", wake_tag="", output=None,
                         summary=None, proof_output=self.root / "proof.json")
        pulls = [[json.loads(json.dumps(stale))], [json.loads(json.dumps(stale))], []]
        with (patch.object(promotion, "__file__", str(self.base / "scripts/toolybara_promotion.py")),
              patch.object(promotion, "_main_sha", return_value=base_sha),
              patch.object(promotion, "base_release_ready", return_value=True),
              patch.object(promotion, "_clone", side_effect=clone),
              patch.object(promotion, "_published_releases", return_value=[
                  {"tag_name": "v0.1.0", "draft": False, "prerelease": False}]),
              patch.object(promotion, "_proof_adapter", return_value=adapter),
              patch.object(promotion, "_fresh_source"),
              patch.object(promotion, "_expected_pull_requests", side_effect=pulls),
              patch.object(promotion, "_gh_request", side_effect=request),
              patch.object(promotion, "_push", side_effect=push),
              patch.dict(os.environ, GH_TOKEN="fixture", GITHUB_RUN_NUMBER="1", GITHUB_RUN_ATTEMPT="1")):
            result = promotion.reconcile(args)
        self.assertEqual((result["state"], result["project"]), ("candidate", "model-router"))
        self.assertEqual(result["pr_number"], 71)
        self.assertEqual(result["base_sha"], base_sha)
        self.assertEqual(result["head_sha"], pushed[-1][1])
        self.assertEqual(len(pushed), 1)
        # The stale PR is closed before the branch push, the push precedes
        # the fresh PR, and the stale PR is never retitled for reuse.
        close_at = next(index for index, call in enumerate(calls)
                        if call[0] == "PATCH" and call[1].endswith("/pulls/65"))
        push_at = next(index for index, call in enumerate(calls)
                       if call[0] == "push")
        post_at = next(index for index, call in enumerate(calls)
                       if call[0] == "POST" and call[1].endswith("/pulls"))
        self.assertEqual(calls[close_at][2], {"state": "closed"})
        self.assertTrue(all(call[2] == {"state": "closed"}
                            for call in calls if call[0] == "PATCH"))
        self.assertLess(close_at, push_at)
        self.assertLess(push_at, post_at)


class EnrollmentTests(unittest.TestCase):
    def test_enrollment_is_explicit_and_paths_cannot_escape(self):
        enrolled_modules = modules(ROOT)
        # Required pre-existing enrollments survive; new approved modules must
        # not force this test to change.
        for required in ("agentsmd", "model-router"):
            self.assertIn(required, enrolled_modules)
        observer = enrolled(ROOT, "agent-observer")
        self.assertEqual(observer["github"], "toolboxmd/agent-observer")
        self.assertEqual(observer["category"], "Developer Tools")
        # Agent Observer ships no Cursor manifest, so enrollment explicitly
        # opts out of Cursor delivery with no runtime paths.
        self.assertIs(observer["cursor"], False)
        self.assertEqual(observer["cursorRuntime"], [])
        with self.assertRaisesRegex(ValueError, "not enrolled"):
            enrolled(ROOT, "../unapproved")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "toolybara").mkdir()
            policy = json.loads((ROOT / "toolybara/modules.json").read_text())
            router = next(entry for entry in policy["modules"] if entry["id"] == "model-router")
            for path in ("../credentials", "/tmp", "SOURCE.json", ".github"):
                router["cursorRuntime"] = [path]
                (root / "toolybara/modules.json").write_text(json.dumps(policy))
                with self.subTest(path=path), self.assertRaises(ValueError):
                    modules(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
