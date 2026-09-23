# Toolybara promotion

Toolybara reconciles the newest Eligible Release of each explicitly enrolled
Agent Module into Marketplace without trusting an event payload or a pull request merely because it is green.
`.github/workflows/toolybara-schedule.yml` owns the hourly trigger and calls the
trusted implementation in `.github/workflows/toolybara-reconciliation.yml` and
`scripts/toolybara_promotion.py`.

## Trigger contract

A source release workflow can send this event to
`toolboxmd/marketplace` with a Toolybara installation token restricted to that
repository and `contents: write`:

```json
{
  "event_type": "module_release_published",
  "client_payload": {
    "release_tag": "v8.6.0"
  }
}
```

`client_payload.release_tag` is only a Wake Hint. The existing
`agentsmd_release_published` event remains supported. Both events reconcile all
enrolled modules; event payloads cannot enroll or select a repository.
Marketplace also reconciles hourly at minute 37 and can be dispatched manually. Every trigger runs in one
non-cancelling concurrency group, so two releases cannot race through separate
merge jobs. The existing `toolybara-agentsmd-promotion` lock key is retained
across upgrades and covers every module, despite its historical name.

## Enrollment

`toolybara/modules.json` is reviewed control-plane policy. Each entry fixes a
module id, exact ToolboxMD source repository, catalog category, whether Cursor
delivery is supported, and any extra released paths needed by that Cursor
package. Native Codex, Claude Code, and Grok Build packages use the complete
source tree pinned by ingestion. Cursor packages include Skills plus approved
runtime paths. AgentsMD retains its existing runtime adapter; Model Router
includes `bin/` and `runner/`.

Enrollment does not publish an unreleased module. The first valid release
creates its catalog entry from this approved identity, then the same ingestion
path owns later updates. Model Router is enrolled but waits for its first valid
release. Modules without Cursor support can set `cursor: false` and an empty
`cursorRuntime`; their native host indexes follow the released Project Record.

Adding a module requires a reviewed policy change and, for Cursor delivery,
its exact `cursor/<module>/*` path in `.toolboxmd/promotion-proof.json`. It does
not require new promotion code, App access, or a host service. Private source
repositories require separately granted read access and are not covered here.

## Reconciliation

Before generating the next patch, reconciliation requires the current `main`
version's stable GitHub Release and exact annotated tag to be published. An
absent or draft release returns `deferred-base-release` without generating,
pushing or opening a candidate. Scheduled or event reconciliation retries later.
An existing tag pointing elsewhere fails closed. This prevents a source-release
event racing the Marketplace base release and making `versionctl` reject the
next patch for skipping an unpublished version anchor.

The reconciliation job starts from the live `main` commit and independently:

1. Visits enrolled modules in policy order and lists each repository's published
   non-draft, non-prerelease releases.
2. Orders stable release tags by SemVer and inspects unreconciled candidates.
3. Peels each tag to its commit and validates the Project Record, record
   digest, version, delivery manifests, referenced documentation, requirements,
   and proof from that same Git tree.
4. Selects the newest valid candidate. An older or stale Wake Hint cannot
   override it.
5. Generates the selected module's catalog and native host indexes, plus its
   Cursor package when enabled, in an ephemeral Marketplace clone. Other
   module records, Cursor entries, and packages remain unchanged.
6. Applies exactly one Marketplace patch transition with `versionctl`.
7. Freezes the final generated commit, including its version transition, before
   proof. A retained equivalent branch is checked out at its exact existing SHA
   before execution; tree equivalence never substitutes for commit identity.
8. Executes the complete suite and deterministic regeneration once, records
   actual commands, results and output digests, then freshly rechecks live state
   before any push. The generated-file allowlist and unrelated records remain
   protected.

Invalid candidates never mutate `main`. Discovery reports an invalid module
and continues to the next enrolled module. One run promotes at most one module;
later scheduled or event runs pick up remaining releases. If no candidate is
available, invalid modules fail with evidence, unpublished modules report
`pending`, and accepted newest releases report `duplicate` with freshly checked
source identity. A failure after candidate generation stops that run. Module
priority rotates with `GITHUB_RUN_NUMBER`, so a module stuck in generation,
proof, or merge cannot keep later modules waiting across workflow runs.
Retries of the same run retain their order. An explicitly selected module
remains the only candidate for that run.

## Expected branch and pull request

Toolybara may create or update only
`toolybara/promote-<module>` for the selected enrolled module. An existing
branch is updated only when exactly one open Toolybara-authored pull request binds it to `main`. A retry with the
same generated tree reuses the existing exact head. The branch is never
deleted.

Only these paths may change:

- `catalog.json`
- `.agents/plugins/marketplace.json`
- `.claude-plugin/marketplace.json`
- `.grok-plugin/marketplace.json`
- `.cursor-plugin/marketplace.json`
- `cursor/<selected-module>/**`, only when admitted by the trusted proof policy
- `VERSION`
- `CHANGELOG.md`

Scripts, workflows, tests, enrollment policy, and other Project records remain
outside the generated allowlist.

## Validation and trusted finalization

The validation job checks out the trusted base and exact candidate head into
separate directories. It reads the live pull request and proves the Toolybara
actor, expected repository and branch, open state, base, exact head SHA,
generated-file allowlist, current newest Eligible Release, peeled source
commit, record digest, module/repository identity, catalog identity, all other
module records and packages, one patch transition, and `versionctl release-check`. It authenticates and reuses
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

For AgentsMD only, after the Toolybara promotion is released, the job comments
on and closes pull request #15 as a superseded manual proposal. It states explicitly that #15 was
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
selected module, source repository, immutable release/commit/record digest,
runtime, Git, runner image, complete tracked input tree, selected argv, exit status, output digests and
execution times. A changed input, failed/incomplete result, dirty checkout,
changed policy or proof older than 24 hours fails closed. Missing artifacts
require a new reconciliation run. Cross-run caching is intentionally unsupported.
A base movement after merge explicitly enters the existing complete moved-base
recovery lane: regeneration and tests execute against the actual merged source,
and the old proof is reported as invalidated rather than reused.

Workflow summaries distinguish execution from reuse and fresh admission. The
artifact retains stdout/stderr and per-check records, including failed checks; its issuer identifies the
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
uninstalled on source repositories. Public source reads use existing read-only
access; promotion writes remain confined to Marketplace.

Marketplace release, distribution, installation, loading, behavioral Live
Verification, and website parity remain separate delivery states.

Failed execution reports the failed command and its original stdout/stderr before
coverage validation. The upload step retains partial proof even when reconciliation
fails; dependent jobs still require successful reconciliation and cannot reuse it.
