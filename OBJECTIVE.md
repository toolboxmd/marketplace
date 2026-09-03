# Objective

Make ToolboxMD Marketplace the reliable distribution path for immutable
ToolboxMD Agent Module releases, beginning with automatic, least-authority
promotion of the newest eligible AgentsMD release.

The Objective is complete when:

- Toolybara has one narrowly authorized GitHub App identity installed only on
  `toolboxmd/marketplace`, with only the minimum metadata, contents, and
  pull-request permissions proven necessary.
- GitHub-hosted event and scheduled reconciliation independently resolve the
  newest eligible immutable AgentsMD release and create or update only
  Toolybara's expected promotion branch and pull request.
- Marketplace validation proves App identity, expected branch and pull request,
  exact head SHA, newest eligible release, generated-file allowlist, catalog
  validity, version transition, and valid, duplicate, missed, invalid, stale,
  competing, serialized, and idempotent cases.
- A trusted final workflow job rechecks the exact validated head and merges it
  with a Toolybara installation token. Failure leaves the pull request open and
  preserves the last-known-good Marketplace state.
- The resulting Marketplace state has exactly one SemVer transition and is
  published through its exact tag and GitHub Release.
- The promoted AgentsMD Project Record and generated Codex, Claude Code, Grok
  Build, and Cursor distributions agree on exact source identity while the
  approved `use-grok` and `karpathy-wiki` releases remain unchanged.
- Distribution, provider publication, installation, loading, behavioral Live
  Verification, and website parity remain separately reported.

Toolybara authority over arbitrary pull requests, Marketplace control-plane
policy, product websites, runtime deployment, provider-owned publication
decisions, unrelated repositories, or broader credentials is outside this
Objective.
