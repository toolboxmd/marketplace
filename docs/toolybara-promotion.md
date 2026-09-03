# Toolybara promotion

Toolybara reconciles the newest Eligible Release from AgentsMD into Marketplace
without trusting an event payload or a pull request merely because it is green.
The implementation lives in
`.github/workflows/toolybara-promotion.yml` and
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
hourly at minute 17 and can be dispatched manually. Every trigger runs in one
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
7. Runs generation twice and requires identical output, the generated-file
   allowlist, preserved non-AgentsMD catalog records, and the complete test
   suite before any push.

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
`karpathy-wiki` records, one patch transition, deterministic regeneration,
complete tests, and `versionctl release-check`.

The Trusted Final Job then reruns the same checks with mergeability required,
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

## Settings and authority boundary

The workflow does not call repository-settings APIs. It does not enable native
auto-merge, branch protection, rulesets, required checks, blocked pushes,
automatic branch deletion, or bypass actors. Toolybara retains only Metadata
read, Contents write, and Pull requests write on Marketplace. It remains
uninstalled on AgentsMD.

Marketplace release, distribution, installation, loading, behavioral Live
Verification, and website parity remain separate delivery states.
