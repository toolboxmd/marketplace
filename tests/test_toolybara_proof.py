#!/usr/bin/env python3
"""Execute once and authenticate exact promotion proof at the command seam."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("toolybara_proof", ROOT / "scripts/toolybara_proof.py")
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)
shared = adapter.shared


class ProofTests(unittest.TestCase):
    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.candidate, stderr=subprocess.DEVNULL).decode().strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "test candidate")
        return self.git("rev-parse", "HEAD")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Tests")
        self.git("config", "user.email", "tests@example.invalid")
        self.counter = self.root / "executions"
        command = ["python3", "-c", "from pathlib import Path; p=Path(" + repr(str(self.counter)) + "); p.write_text(p.read_text()+'x' if p.exists() else 'x')"]
        self.policy = copy.deepcopy(adapter.policy())
        for check in self.policy["checks"].values():
            check["argv"] = command
        (self.candidate / ".toolboxmd").mkdir()
        (self.candidate / adapter.POLICY_PATH).write_text(json.dumps(self.policy))
        (self.candidate / "catalog.json").write_text('{"version":1}')
        self.base_sha = self.commit()
        self.base = self.root / "base"
        subprocess.run(["git", "clone", "-q", str(self.candidate), str(self.base)], check=True)
        (self.candidate / "catalog.json").write_text('{"version":2}')
        self.head = self.commit()
        self.source = {"release": "v9.0.0", "commit": "a" * 40, "recordSha256": "b" * 64}
        self.expected = adapter.identity(self.base_sha, self.head, self.source)
        self.env = {
            "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "toolboxmd/marketplace",
            "GITHUB_SHA": self.base_sha, "GITHUB_WORKFLOW_SHA": self.base_sha,
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
            "TOOLYBARA_PROOF_ATTEMPT": "1",
            "GITHUB_WORKFLOW_REF": "toolboxmd/marketplace/.github/workflows/toolybara-reconciliation.yml@refs/heads/main",
        }
        self.addCleanup(patch.stopall)
        patch.object(adapter, "policy", return_value=self.policy).start()
        patch.dict(os.environ, self.env).start()
        self.output = self.root / "proof"

    def record(self):
        return adapter.record(self.base, self.candidate, self.root / "source", self.expected, self.output)

    def reuse(self, expected=None, digest=None):
        return adapter.reuse(self.base, self.candidate, expected or self.expected,
                             self.output / "proof.json", digest or self.receipt["sha256"])

    def test_exact_complete_execution_is_reused_twice_without_test_execution(self):
        self.receipt = self.record()
        self.assertEqual(self.counter.read_text(), "xx")
        for _ in range(2):
            result = self.reuse()
            self.assertEqual(result["executedHere"], [])
            self.assertEqual(result["reusedHere"], ["generated", "suite"])
        self.assertEqual(self.counter.read_text(), "xx")

    def test_altered_forged_and_missing_transport_are_rejected(self):
        self.receipt = self.record()
        raw = (self.output / "proof.json").read_bytes()
        (self.output / "proof.json").write_bytes(raw + b" ")
        with self.assertRaisesRegex(shared.ProofError, "authenticated reconciliation"):
            self.reuse()
        with self.assertRaisesRegex(shared.ProofError, "protected reconciliation"):
            adapter.reuse(self.base, self.candidate, self.expected, self.output / "proof.json", None)
        (self.output / "proof.json").write_bytes(raw)
        with patch.dict(os.environ, {"GITHUB_WORKFLOW_REF": "attacker/repo/.github/workflows/fake.yml@refs/heads/main"}):
            with self.assertRaisesRegex(shared.ProofError, "unauthorized proof workflow"):
                self.reuse()
        with patch.dict(os.environ, {"TOOLYBARA_PROOF_ATTEMPT": "2"}):
            with self.assertRaisesRegex(shared.ProofError, "issuer"):
                self.reuse()

    def test_source_release_digest_base_head_and_environment_invalidate(self):
        self.receipt = self.record()
        for key, value in {"source": "c" * 40, "recordSha256": "c" * 64, "release": "v10.0.0", "base": self.head, "head": self.base_sha}.items():
            with self.subTest(key=key), self.assertRaises(shared.ProofError):
                self.reuse({**self.expected, key: value})
        with patch.dict(os.environ, {"ImageVersion": "changed"}):
            with self.assertRaisesRegex(shared.ProofError, "environment"):
                self.reuse()

    def test_authentic_failed_incomplete_or_stale_records_cannot_pass(self):
        self.receipt = self.record()
        original = json.loads((self.output / "proof.json").read_bytes())
        for change in ("failed", "incomplete", "stale"):
            record = copy.deepcopy(original)
            if change == "failed":
                record["results"]["suite"]["exitCode"] = 1
            elif change == "incomplete":
                del record["results"]["suite"]
            else:
                record["started"] -= 86401
                record["finished"] -= 86401
            raw = shared.encode(record)
            (self.output / "proof.json").write_bytes(raw)
            with self.subTest(change=change), self.assertRaises(shared.ProofError):
                self.reuse(digest=shared.digest(raw))

    def test_remote_tag_movement_during_proof_is_rejected_before_mutation(self):
        spec = importlib.util.spec_from_file_location("promotion", ROOT / "scripts/toolybara_promotion.py")
        promotion = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(promotion)
        self.git("tag", "v9.0.0", self.head)
        subprocess.run(["git", "fetch", "-q", "--tags", "origin"], cwd=self.base, check=True)
        (self.candidate / "catalog.json").write_text('{"version":3}')
        moved = self.commit()
        self.git("tag", "-f", "v9.0.0", moved)
        def inspect(_control, source, tag):
            commit = subprocess.check_output(["git", "rev-parse", tag], cwd=source).decode().strip()
            return {"release": tag, "commit": commit, "recordSha256": "b" * 64}
        with patch.object(promotion, "_published_releases", return_value=[{"tag_name": "v9.0.0", "draft": False, "prerelease": False}]), patch.object(promotion, "_current_release", return_value="v8.0.0"), patch.object(promotion, "_inspect_release", side_effect=inspect):
            with self.assertRaisesRegex(promotion.PromotionError, "identity moved"):
                promotion._fresh_source(self.base, self.base, {**self.source, "commit": self.head})
        self.assertEqual(subprocess.check_output(["git", "rev-parse", "v9.0.0"], cwd=self.base).decode().strip(), moved)

    def test_policy_control_tests_and_unknown_paths_never_expand_generated_scope(self):
        for path in ("scripts/forged.py", "tests/forged.py", ".github/workflows/forged.yml", "unrelated.txt", adapter.POLICY_PATH):
            with self.subTest(path=path):
                self.git("reset", "--hard", self.head)
                target = self.candidate / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("{}")
                changed = self.commit()
                with self.assertRaises(shared.ProofError):
                    adapter.admit(self.base, self.candidate, {**self.expected, "head": changed})


class WorkflowTests(unittest.TestCase):
    def test_validator_pin_and_generated_allowlist_are_exact(self):
        lock = json.loads((ROOT / "scripts/vendor/agentsmd-scoped-proof.json").read_text())
        self.assertEqual(hashlib.sha256((ROOT / "scripts/vendor/scoped_proof.py").read_bytes()).hexdigest(), lock["sha256"])
        policy = adapter.policy()
        self.assertEqual(policy["checks"]["suite"]["argv"], ["bash", "tests/run-all.sh"])
        self.assertEqual(set(policy["rules"][0]["paths"]), {
            "catalog.json", ".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json",
            ".cursor-plugin/marketplace.json", ".grok-plugin/marketplace.json", "plugins/agentsmd/*", "VERSION", "CHANGELOG.md",
        })

    def test_same_run_transport_has_no_candidate_selected_run_or_permissions(self):
        workflow = (ROOT / ".github/workflows/toolybara-reconciliation.yml").read_text()
        self.assertEqual(workflow.count("actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093"), 2)
        self.assertNotIn("run-id:", workflow)
        self.assertNotIn("actions: write", workflow)
        self.assertNotIn("actions: read", workflow)
        self.assertEqual(workflow.count("TOOLYBARA_PROOF_DIGEST: ${{ needs.reconcile.outputs.proof_sha256 }}"), 2)
        self.assertIn("proof_attempt: ${{ steps.reconcile.outputs.proof_attempt }}", workflow)
        self.assertIn("if: needs.validate.result == 'success'", workflow)


if __name__ == "__main__":
    unittest.main(verbosity=2)
