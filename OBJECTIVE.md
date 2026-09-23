# Objective

Make ToolboxMD Marketplace the reliable automatic distribution path for immutable releases of explicitly approved ToolboxMD Agent Modules.

The Objective is complete when:

- Toolybara promotes approved modules through one shared, serialized workflow using a GitHub App installed only on `toolboxmd/marketplace`, with the minimum required permissions.
- Event and scheduled reconciliation independently resolve eligible releases. Each release supplies a valid Project Record and complete plugin package. Modules without an eligible release remain unpublished.
- Validation binds the selected module, repository, release, source commit, Project Record digest, generated paths, pull request, and exact head. Every other module remains unchanged.
- Trusted finalization rechecks the validated candidate, merges only generated promotion changes, and publishes exactly one Marketplace SemVer transition through its exact tag and GitHub Release.
- AgentsMD and Model Router both complete the shared path, and duplicate, missed, invalid, stale, competing, and interrupted promotions preserve the last valid distribution.
- Supported host distributions agree on source identity. Distribution, provider publication, installation, loading, behavioral Live Verification, and website parity are reported separately.

Automatic enrollment, source-repository releases, arbitrary pull requests, Marketplace control-plane changes, product websites, runtime deployment, broader credentials, and installation without granted authority remain outside this Objective.
