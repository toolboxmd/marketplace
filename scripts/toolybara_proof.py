#!/usr/bin/env python3
"""Trusted same-run proof transport for the generated Toolybara promotion lane."""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ".toolboxmd/promotion-proof.json"
SPEC = importlib.util.spec_from_file_location("agentsmd_scoped_proof", ROOT / "scripts/vendor/scoped_proof.py")
assert SPEC and SPEC.loader
shared = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shared)


def policy():
    lock = shared.decode((ROOT / "scripts/vendor/agentsmd-scoped-proof.json").read_bytes())
    shared.require(shared.digest((ROOT / "scripts/vendor/scoped_proof.py").read_bytes()) == lock["sha256"],
                   "pinned shared validator changed")
    return shared.decode((ROOT / POLICY_PATH).read_bytes())


def workflow_identity(base):
    """These values come from the protected workflow, never the downloaded record."""
    env = os.environ
    shared.require(env.get("GITHUB_ACTIONS") == "true" and
                   env.get("GITHUB_REPOSITORY") == "toolboxmd/marketplace" and
                   env.get("GITHUB_SHA") == base and
                   env.get("GITHUB_WORKFLOW_SHA") == base,
                   "proof transport requires the trusted Marketplace workflow revision")
    shared.require(env.get("GITHUB_EVENT_NAME") in {"schedule", "workflow_dispatch", "repository_dispatch"},
                   "unauthorized proof workflow event")
    shared.require(env.get("GITHUB_WORKFLOW_REF") in {
        "toolboxmd/marketplace/.github/workflows/toolybara-reconciliation.yml@refs/heads/main",
        "toolboxmd/marketplace/.github/workflows/toolybara-schedule.yml@refs/heads/main",
    }, "unauthorized proof workflow")
    run = env.get("GITHUB_RUN_ID", "")
    attempt = env.get("TOOLYBARA_PROOF_ATTEMPT", env.get("GITHUB_RUN_ATTEMPT", ""))
    shared.require(bool(re.fullmatch(r"[1-9][0-9]*", run)) and
                   bool(re.fullmatch(r"[1-9][0-9]*", attempt)), "missing authenticated run identity")
    return f"github:toolboxmd/marketplace:{run}:{attempt}:reconcile"


def observer(base_root, candidate_root, identity):
    """Observe actual runtime and pinned inputs rather than trusting old fields."""
    def observe(_name):
        return {
            "python": platform.python_version(),
            "platform": f"{platform.system()}:{platform.machine()}",
            "git": subprocess.check_output(["git", "--version"], text=True).strip(),
            "runnerImage": os.environ.get("ImageOS", "local") + ":" + os.environ.get("ImageVersion", "local"),
            "identity": shared.digest(shared.encode(identity)),
            "control": shared.source_inputs(base_root, identity["base"], ["scripts/*", ".github/*", ".toolboxmd/*", "tests/*", ".version-policy.json"]),
            "candidateTree": shared.git(candidate_root, "rev-parse", identity["head"] + "^{tree}").decode().strip(),
        }
    return observe


def identity(base, head, source):
    return {"base": base, "head": head, "release": source["release"],
            "source": source["commit"], "recordSha256": source["recordSha256"]}


def admit(base_root, candidate_root, expected):
    """Generated admission is separate from a candidate's complete proof baseline."""
    p = policy()
    shared.clean_candidate(base_root, expected["base"])
    shared.clean_candidate(candidate_root, expected["head"])
    shared.require(shared.decode(shared.git(base_root, "show", expected["base"] + ":" + POLICY_PATH)) == p,
                   "control must match the separately trusted base policy")
    # This cumulative base-to-head classification blocks policy, control-plane,
    # test, permission and unknown changes even though complete proof anchors HEAD.
    return shared.select(candidate_root, expected["base"], expected["head"], p)


def record(base_root, candidate_root, source_root, expected, output):
    admit(base_root, candidate_root, expected)
    issuer = workflow_identity(expected["base"])
    # check-generated runs only from admitted unchanged control. No credentials
    # or external state are supplied as proof inputs.
    previous = {key: os.environ.get(key) for key in ("TOOLYBARA_PROOF_CONTEXT", "PYTHONDONTWRITEBYTECODE")}
    os.environ["TOOLYBARA_PROOF_CONTEXT"] = json.dumps({
        "baseRoot": str(base_root), "sourceRoot": str(source_root), "identity": expected,
    })
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        raw = shared.run(candidate_root, expected["head"], expected["head"], policy(),
                         mode="complete", observe=observer(base_root, candidate_root, expected),
                         output=output, issuer=issuer)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    # Report the executed failure before coverage validation can mask it as an
    # incomplete record. Keep exact logs beside proof.json for artifact upload.
    for name, result in shared.decode(raw)["results"].items():
        if result["exitCode"]:
            for stream in ("stdout", "stderr"):
                log = Path(output) / name / stream
                print(f"Proof command {name} {stream}:\n{log.read_text(errors='replace')}", file=sys.stderr)
            raise shared.ProofError(f"proof command {name} failed (exit {result['exitCode']}); execution logs retained")

    # Exact bytes returned by our protected executor are authenticated here.
    def executed(data):
        shared.require(data == raw, "execution bytes changed")
        return issuer
    result = shared.validate_complete(candidate_root, expected["head"], policy(), raw,
                                      authenticate=executed, observe=observer(base_root, candidate_root, expected))
    return {"sha256": shared.digest(raw), "proof": result,
            "seconds": shared.decode(raw)["finished"] - shared.decode(raw)["started"]}


def reuse(base_root, candidate_root, expected, proof_path, expected_digest):
    admit(base_root, candidate_root, expected)
    issuer = workflow_identity(expected["base"])
    # The artifact is downloaded by a SHA-pinned action from THIS workflow run,
    # after needs.reconcile succeeded. The expected digest is a protected job
    # output, not a field in the artifact or a candidate-controlled argument.
    shared.require(isinstance(expected_digest, str) and
                   bool(re.fullmatch(r"[a-f0-9]{64}", expected_digest)),
                   "missing protected reconciliation proof digest")
    raw = proof_path.read_bytes()
    def authenticate(data):
        shared.require(shared.digest(data) == expected_digest, "proof differs from authenticated reconciliation output")
        return issuer
    result = shared.validate_complete(candidate_root, expected["head"], policy(), raw,
                                      authenticate=authenticate, observe=observer(base_root, candidate_root, expected))
    record_data = shared.decode(raw)
    return {"executedHere": [], "reusedHere": sorted(record_data["results"]),
            "execution": result, "issuer": issuer, "seconds": record_data["finished"] - record_data["started"]}


def check_generated():
    context = json.loads(os.environ["TOOLYBARA_PROOF_CONTEXT"])
    expected = context["identity"]
    base = Path(context["baseRoot"])
    source = Path(context["sourceRoot"])
    candidate = Path.cwd()
    admit(base, candidate, expected)
    spec = importlib.util.spec_from_file_location("promotion", ROOT / "scripts/toolybara_promotion.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source_identity = module._inspect_release(base, source, expected["release"])
    shared.require(identity(expected["base"], expected["head"], source_identity) == expected,
                   "generation source identity changed")
    module.validate_candidate_state(base, candidate, source_identity)
    module._regenerate_and_compare(base, candidate, source, source_identity)
    module._run(str(base / "plugins/agentsmd/tools/versionctl/bin/versionctl"), "release-check", cwd=candidate)
    print(json.dumps({"generation": "deterministic", "identity": expected, "preserved": "non-AgentsMD records"}))


if __name__ == "__main__":
    if sys.argv[1:] != ["check-generated"]:
        raise SystemExit("expected check-generated")
    check_generated()
