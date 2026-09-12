# Toolybara promotion

Toolybara reconciles the newest Eligible Release from AgentsMD into Marketplace
without trusting an event payload or a pull request merely because it is green.
`.github/workflows/toolybara-schedule.yml` owns the hourly trigger and calls the
trusted implementation in `.github/workflows/toolybara-reconciliation.yml` and
`scripts/toolybara_promotion.py`.

## Trigger contract

The AgentsMD release workflow sends this event to
`toolboxmd/marketplace` with a Toolybara installation token restricted to that
repository and `contents: write`:

```json
{
  "event_type": "agentsmd_release_published",
  "client_payload": {
    "release_tag": "v8.6.0"
  }
}
```

`client_payload.release_tag` is only a Wake Hint. Marketplace also reconciles
hourly at minute 37 and can be dispatched manually. Every trigger runs in one
non-cancelling concurrency group, so two releases cannot race through separate
merge jobs.

## Reconciliation

The reconciliation job starts from the live `main` commit and independently:

1. Lists published non-draft, non-prerelease AgentsMD releases.
2. Orders stable release tags by SemVer and inspects unreconciled candidates.
3. Peels each tag to its commit and validates the Project Record, record
   digest, version, delivery manifests, referenced documentation, requirements,
   and proof from that same Git tree.
4. Selects the newest valid candidate. An older or stale Wake Hint cannot
   override it.
5. Generates the catalog, Codex, Claude Code, Grok Build, Cursor index, and
   Cursor package in an ephemeral Marketplace clone.
6. Applies exactly one Marketplace patch transition with `versionctl`.
7. Freezes the final generated commit, including its version transition, before
   proof. A retained equivalent branch is checked out at its exact existing SHA
   before execution; tree equivalence never substitutes for commit identity.
8. Executes the complete suite and deterministic regeneration once, records
   actual commands, results and output digests, then freshly rechecks live state
   before any push. The generated-file allowlist and unrelated records remain
   protected.

Invalid candidates never mutate `main`. If no unreconciled candidate is valid,
the run fails with the rejection evidence. If the accepted release is already
newest, the run exits as a duplicate no-op.

## Expected branch and pull request

Toolybara may create or update only
`toolybara/promote-agentsmd`. An existing branch is updated only when exactly
one open Toolybara-authored pull request binds it to `main`. A retry with the
same generated tree reuses the existing exact head. The branch is never
deleted.

Only these paths may change:

- `catalog.json`
- `.agents/plugins/marketplace.json`
- `.claude-plugin/marketplace.json`
- `.grok-plugin/marketplace.json`
- `.cursor-plugin/marketplace.json`
- `plugins/agentsmd/**`
- `VERSION`
- `CHANGELOG.md`

Scripts, workflows, tests, and other Project records are outside the generated
allowlist.

## Validation and trusted finalization

The validation job checks out the trusted base and exact candidate head into
separate directories. It reads the live pull request and proves the Toolybara
actor, expected repository and branch, open state, base, exact head SHA,
generated-file allowlist, current newest Eligible Release, peeled source
commit, record digest, catalog identity, preserved `use-grok` and
`karpathy-wiki` records, one patch transition, and `versionctl release-check`. It authenticates and reuses
the exact reconciliation execution record for deterministic regeneration and
complete tests. No tests execute again in validation or ordinary finalization.

The Trusted Final Job reuses the same complete execution proof and repeats the
live checks with mergeability required,
rereads the pull request and live `main`, and mints a fresh Toolybara token. It
calls GitHub's pull-request merge API with `merge_method: squash` and the exact
validated `sha`. It rereads the merged pull request and requires Toolybara to be
the merge actor. If `main` moved in the final API race window, it checks out the
actual squash parent and fully revalidates the generated-only merged state
against that parent before creating the annotated version tag and GitHub
Release.

If the head, base, actor, branch, candidate, or generated scope changes before
the merge call, the job fails and leaves the pull request open. If release
creation fails after a successful merge, rerunning the failed job recognizes
only the same Toolybara-authored and Toolybara-merged head, revalidates any
moved-base result, and resumes exact tag and release creation idempotently.

After the Toolybara promotion is released, the job comments on and closes pull
request #15 as a superseded manual proposal. It states explicitly that #15 was
not merged and was not automatic delivery, then rereads #15 to prove it is
closed and unmerged.

## Exact candidate proof

`.toolboxmd/promotion-proof.json` is the reviewed generated-promotion scope. It
uses precisely the generated allowlist above. Scripts, workflows, tests, policy,
permissions, unknown paths and unrelated Project records cannot expand this lane.
The cumulative trusted-base-to-candidate diff is admitted independently of proof.

The shared implementation is vendored unchanged from AgentsMD commit
`5ce0dd9cefaf31c8c14ef637bc71c5038f4aadb4`, with its source and byte digest in
`scripts/vendor/agentsmd-scoped-proof.json`. The source interface is
`docs/scoped-proof.md`, schema 1, `run` and `validate_complete`. Marketplace loads
both adapter and policy from its pinned trusted base, never from PR-selected
control. This pin does not claim AgentsMD release, installation or loading.

The first candidate containing the policy receives its own direct complete
proof. Reconciliation runs `bash tests/run-all.sh` and
`python3 scripts/toolybara_proof.py check-generated` on that clean, versioned
commit. The second command checks two deterministic regenerations against the
frozen tree, unrelated catalog preservation, immutable source and version.
There is no historical baseline relabeling, scoped-baseline chain, fabricated
empty record or tree-to-commit exception. All required coverage runs once;
this adapter reuses complete proof across jobs rather than skipping unrelated
checks within that initial execution.

The protected reconciliation job publishes a same-run immutable Actions artifact
and exposes the record digest and producing attempt through trusted job outputs.
SHA-pinned `download-artifact` steps select only that artifact in the current run,
after successful reconciliation. They do not accept another run or repository.
The adapter binds downloaded bytes to that protected digest, repository, allowed
workflow at `main`, exact workflow revision, run and producing attempt. The
record's issuer or digest alone does not authenticate evidence. Job retries use
the original producing attempt; full workflow reruns create new evidence.
No additional GitHub token or App permissions are required.

Records bind the exact candidate, base, policy, generator/control inputs,
immutable AgentsMD release/commit/record digest, runtime, Git, runner image,
complete tracked input tree, selected argv, exit status, output digests and
execution times. A changed input, failed/incomplete result, dirty checkout,
changed policy or proof older than 24 hours fails closed. Missing artifacts
require a new reconciliation run. Cross-run caching is intentionally unsupported.
A base movement after merge explicitly enters the existing complete moved-base
recovery lane: regeneration and tests execute against the actual merged source,
and the old proof is reported as invalidated rather than reused.

Workflow summaries distinguish execution from reuse and fresh admission. The
artifact retains stdout/stderr and per-check records; its issuer identifies the
run and producing attempt, and summaries report elapsed verification seconds.
GitHub's job timeline supplies runner time and stage/coordination gaps. There is
no production build, deployment, request-to-live measurement or provider
publication in this proof path. Finalization still proves the unchanged merged
tree (or performs complete moved-base proof), exact tag and GitHub Release.

Algorithm decision: Issue #39 owns the requirement to remove repeated execution
without weakening promotion admission. Delete duplicate suite and regeneration
runs in ordinary validation/finalization. Retain one complete frozen-candidate
execution, generated scope, preservation, version checks and fresh external
state because each proves a distinct requirement. Use the existing same-run
artifact transport and the shared complete-proof validator as the smallest
surviving path. Focused command tests shorten feedback; automation applies only
to the already authorized Toolybara loop. Website impact is none: this changes
internal proof execution without changing public distribution or setup behavior.

## Settings and authority boundary

The workflow does not call repository-settings APIs. It does not enable native
auto-merge, branch protection, rulesets, required checks, blocked pushes,
automatic branch deletion, or bypass actors. Toolybara retains only Metadata
read, Contents write, and Pull requests write on Marketplace. It remains
uninstalled on AgentsMD.

Marketplace release, distribution, installation, loading, behavioral Live
Verification, and website parity remain separate delivery states.
